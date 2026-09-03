"""Detección de productos y espacios vacíos en una foto de góndola.

Dos problemas hacen que un solo pase de un modelo genérico no sirva:

1. Los productos son pequeños respecto a la foto completa, así que la imagen se
   recorre en mosaicos solapados y los resultados se fusionan con NMS.
2. Ninguna red sola cubre bien todos los tipos de estante. Se combinan dos:
   - `shelf-yolov8`, entrenado en góndolas reales (SKU-110K), que además distingue
     el espacio vacío (agotado) del producto.
   - `yolov8s-worldv2`, de vocabulario abierto, que rescata empaques que el otro
     pierde (bolsas, cajas grandes, tomas en ángulo).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PIL import Image

# Vocabulario abierto: YOLO-World acepta clases por texto, sin reentrenar.
CLASES_ABIERTAS = ["product", "bottle", "box", "package", "can", "jar", "carton"]

_cache: dict[str, object] = {}


def _modelo(nombre: str):
    if nombre not in _cache:
        from ultralytics import YOLO

        if nombre == "gondola":
            _cache[nombre] = YOLO("modelos/shelf-yolov8.pt")
        else:
            m = YOLO("modelos/yolov8s-worldv2.pt")
            m.set_classes(CLASES_ABIERTAS)
            _cache[nombre] = m
    return _cache[nombre]


def precargar() -> None:
    """Carga los pesos al arrancar, para que la primera foto no espere."""
    _modelo("gondola")
    _modelo("abierto")


@dataclass
class Deteccion:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    tipo: str            # "producto" | "vacio"
    fuente: str          # modelo que la encontró
    marca: bool = False  # marcada como producto de la marca auditada
    fila: int = -1

    @property
    def ancho(self) -> float:
        return self.x2 - self.x1

    @property
    def alto(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return max(0.0, self.ancho) * max(0.0, self.alto)

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    def dict(self) -> dict:
        return {
            "x1": round(self.x1, 1), "y1": round(self.y1, 1),
            "x2": round(self.x2, 1), "y2": round(self.y2, 1),
            "conf": round(self.conf, 3), "tipo": self.tipo,
            "fuente": self.fuente, "marca": self.marca, "fila": self.fila,
        }


# ---------------------------------------------------------------- geometría

def _nms(dets: list[Deteccion], umbral: float = 0.45) -> list[Deteccion]:
    if not dets:
        return []
    cajas = np.array([[d.x1, d.y1, d.x2, d.y2] for d in dets], dtype=float)
    scores = np.array([d.conf for d in dets])
    areas = (cajas[:, 2] - cajas[:, 0]) * (cajas[:, 3] - cajas[:, 1])
    orden = scores.argsort()[::-1]
    guardadas: list[int] = []
    while orden.size:
        i = int(orden[0])
        guardadas.append(i)
        if orden.size == 1:
            break
        resto = orden[1:]
        xx1 = np.maximum(cajas[i, 0], cajas[resto, 0])
        yy1 = np.maximum(cajas[i, 1], cajas[resto, 1])
        xx2 = np.minimum(cajas[i, 2], cajas[resto, 2])
        yy2 = np.minimum(cajas[i, 3], cajas[resto, 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        iou = inter / (areas[i] + areas[resto] - inter + 1e-9)
        orden = resto[iou <= umbral]
    return [dets[i] for i in guardadas]


def _quitar_contenedoras(dets: list[Deteccion]) -> list[Deteccion]:
    """Elimina la caja grande que envuelve a varias pequeñas.

    Pasa cuando el modelo marca un bloque entero de productos iguales como uno
    solo; para contar facings esa caja sobra y las de adentro son las buenas.
    """
    if len(dets) < 3:
        return dets
    cajas = np.array([[d.x1, d.y1, d.x2, d.y2] for d in dets], dtype=float)
    areas = np.array([d.area for d in dets])
    fuera = set()
    for i in range(len(dets)):
        if i in fuera:
            continue
        xx1 = np.maximum(cajas[i, 0], cajas[:, 0])
        yy1 = np.maximum(cajas[i, 1], cajas[:, 1])
        xx2 = np.minimum(cajas[i, 2], cajas[:, 2])
        yy2 = np.minimum(cajas[i, 3], cajas[:, 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        # cuánto de cada caja j queda dentro de i
        dentro = inter / (areas + 1e-9)
        contenidas = [j for j in range(len(dets))
                      if j != i and dentro[j] > 0.85 and areas[j] < areas[i] * 0.6]
        if len(contenidas) >= 2:
            fuera.add(i)
    return [d for k, d in enumerate(dets) if k not in fuera]


def _filtrar_desmesuradas(dets: list[Deteccion]) -> list[Deteccion]:
    """Descarta cajas gigantes: un facing no puede ser media góndola.

    Se usa la mediana como referencia porque es robusta a los propios atípicos
    que se quieren eliminar.
    """
    if len(dets) < 6:
        return dets
    mediana = float(np.median([d.area for d in dets]))
    return [d for d in dets if d.area <= mediana * 10]


def _mosaicos(ancho: int, alto: int, lado: int, solape: float = 0.25):
    paso = max(1, int(lado * (1 - solape)))
    xs = list(range(0, max(ancho - lado, 0) + 1, paso)) or [0]
    ys = list(range(0, max(alto - lado, 0) + 1, paso)) or [0]
    if xs[-1] + lado < ancho:
        xs.append(ancho - lado)
    if ys[-1] + lado < alto:
        ys.append(alto - lado)
    for y in ys:
        for x in xs:
            yield max(0, x), max(0, y), min(ancho, x + lado), min(alto, y + lado)


# ---------------------------------------------------------------- detección

def _pasar(modelo, nombre_fuente: str, img: Image.Image, conf: float,
           tiling: bool, imgsz: int) -> list[Deteccion]:
    ancho, alto = img.size
    if tiling:
        lado = max(640, int(min(ancho, alto) / 1.5))
        ventanas = list(_mosaicos(ancho, alto, lado))
    else:
        ventanas = [(0, 0, ancho, alto)]

    recortes = [img.crop(v) for v in ventanas]
    salida: list[Deteccion] = []
    for i in range(0, len(recortes), 4):
        lote = recortes[i:i + 4]
        res = modelo.predict(lote, conf=conf, iou=0.5, imgsz=imgsz,
                             verbose=False, max_det=600)
        for k, r in enumerate(res):
            ox, oy = ventanas[i + k][0], ventanas[i + k][1]
            for caja in r.boxes:
                bx = caja.xyxy[0].tolist()
                etiqueta = modelo.names[int(caja.cls[0])]
                salida.append(Deteccion(
                    x1=bx[0] + ox, y1=bx[1] + oy, x2=bx[2] + ox, y2=bx[3] + oy,
                    conf=float(caja.conf[0]),
                    tipo="vacio" if etiqueta == "empty" else "producto",
                    fuente=nombre_fuente,
                ))
    return salida


def _agrupar_filas(dets: list[Deteccion], alto_img: int) -> None:
    """Asigna a cada detección la balda del estante a la que pertenece.

    Se agrupa solo con los productos, por centro vertical: si dos están a menos de
    una altura de producto uno del otro, van en la misma balda. Los espacios vacíos
    no forman baldas propias — se asignan a la balda de producto más cercana, porque
    un hueco siempre está *en* una balda, y si no se hace así aparecen baldas
    fantasma con cero productos.
    """
    productos = sorted([d for d in dets if d.tipo == "producto"], key=lambda d: d.cy)
    if not productos:
        for d in dets:
            d.fila = 0
        return

    alto_tipico = float(np.median([d.alto for d in productos]))
    tolerancia = max(alto_tipico * 0.5, alto_img * 0.012)

    grupos: list[list[Deteccion]] = [[productos[0]]]
    for d in productos[1:]:
        if d.cy - grupos[-1][-1].cy > tolerancia:
            grupos.append([])
        grupos[-1].append(d)

    # Una balda con una sola cara suele ser un recorte mal ubicado, no una balda:
    # se funde con la vecina más cercana si está a menos de dos alturas.
    cambio = True
    while cambio and len(grupos) > 1:
        cambio = False
        for i, g in enumerate(grupos):
            if len(g) > 1:
                continue
            vecinos = [j for j in (i - 1, i + 1) if 0 <= j < len(grupos)]
            if not vecinos:
                continue
            centro = float(np.mean([x.cy for x in g]))
            j = min(vecinos, key=lambda k: abs(np.mean([x.cy for x in grupos[k]]) - centro))
            if abs(float(np.mean([x.cy for x in grupos[j]])) - centro) <= alto_tipico * 1.2:
                grupos[j].extend(g)
                grupos.pop(i)
                cambio = True
                break

    grupos.sort(key=lambda g: float(np.mean([x.cy for x in g])))
    centros = [float(np.mean([x.cy for x in g])) for g in grupos]
    for n, g in enumerate(grupos):
        for d in g:
            d.fila = n
    for d in dets:
        if d.tipo == "vacio":
            d.fila = int(np.argmin([abs(c - d.cy) for c in centros]))


def detectar(ruta: str, conf: float = 0.06, tiling: bool = True,
             ensamble: bool = True) -> tuple[list[Deteccion], dict]:
    t0 = time.time()
    img = Image.open(ruta).convert("RGB")
    ancho, alto = img.size

    dets = _pasar(_modelo("gondola"), "gondola", img, conf, tiling, 1280)
    n_gondola = len(dets)
    n_abierto = 0
    if ensamble:
        abiertas = _pasar(_modelo("abierto"), "abierto", img, max(conf, 0.08), tiling, 960)
        n_abierto = len(abiertas)
        dets += abiertas

    vacios = _nms([d for d in dets if d.tipo == "vacio"], 0.4)
    productos = _nms([d for d in dets if d.tipo == "producto"], 0.4)
    productos = _filtrar_desmesuradas(_quitar_contenedoras(productos))

    final = productos + vacios
    _agrupar_filas(final, alto)

    meta = {
        "ancho": ancho, "alto": alto,
        "segundos": round(time.time() - t0, 2),
        "crudas_gondola": n_gondola, "crudas_abierto": n_abierto,
        "productos": len(productos), "vacios": len(vacios),
        "filas": (max((d.fila for d in final), default=-1) + 1),
    }
    return final, meta

"""Cálculo de los indicadores de una auditoría de góndola.

El mercaderista hoy hace esto a ojo: cuenta cuántas caras (facings) tiene su marca,
cuántas el total, y anota si algo está agotado. Aquí sale de la foto.
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def similares(ruta: str, dets, indices_semilla: list[int], umbral: float = 0.88) -> list[int]:
    """Dado uno o más productos marcados a mano, encuentra los demás iguales.

    En una góndola las caras de una misma referencia son fotos casi idénticas del
    mismo empaque, así que basta comparar histogramas de color en HSV: es robusto a
    los cambios de brillo entre la balda de arriba y la de abajo, y no necesita
    entrenar nada ni salir a internet.
    """
    productos = [i for i, d in enumerate(dets) if d.tipo == "producto"]
    if not indices_semilla or not productos:
        return []
    img = Image.open(ruta).convert("RGB")

    def firma(i: int) -> np.ndarray:
        d = dets[i]
        recorte = img.crop((d.x1, d.y1, d.x2, d.y2)).convert("HSV").resize((48, 48))
        a = np.asarray(recorte, dtype=np.float32)
        h = np.histogram(a[:, :, 0], bins=24, range=(0, 256))[0]
        s = np.histogram(a[:, :, 1], bins=12, range=(0, 256))[0]
        v = np.histogram(a[:, :, 2], bins=12, range=(0, 256))[0]
        f = np.concatenate([h, s, v])
        return f / (np.linalg.norm(f) + 1e-9)

    semillas = [firma(i) for i in indices_semilla if dets[i].tipo == "producto"]
    if not semillas:
        return []
    encontrados = []
    for i in productos:
        f = firma(i)
        if max(float(f @ s) for s in semillas) >= umbral:
            encontrados.append(i)
    return sorted(set(encontrados) | set(indices_semilla))


def indicadores(dets, meta: dict, objetivo_share: float | None = None) -> dict:
    productos = [d for d in dets if d.tipo == "producto"]
    vacios = [d for d in dets if d.tipo == "vacio"]
    de_marca = [d for d in productos if d.marca]

    total = len(productos)
    share = (len(de_marca) / total * 100) if total else 0.0

    # Share por área ocupada, no solo por número de caras: un producto grande pesa
    # más en el lineal que uno pequeño, y es como lo mide trade marketing.
    area_total = sum(d.area for d in productos) or 1.0
    share_area = sum(d.area for d in de_marca) / area_total * 100

    area_vacia = sum(d.area for d in vacios)
    ocupacion = area_total / (area_total + area_vacia) * 100 if (area_total + area_vacia) else 100.0

    filas: dict[int, dict] = {}
    for d in dets:
        f = filas.setdefault(d.fila, {"balda": d.fila + 1, "productos": 0, "marca": 0, "vacios": 0})
        if d.tipo == "vacio":
            f["vacios"] += 1
        else:
            f["productos"] += 1
            f["marca"] += int(d.marca)

    res = {
        "facings_totales": total,
        "facings_marca": len(de_marca),
        "share_of_shelf": round(share, 1),
        "share_por_area": round(share_area, 1),
        "agotados": len(vacios),
        "ocupacion_lineal": round(ocupacion, 1),
        "baldas": sorted(filas.values(), key=lambda f: f["balda"]),
        "segundos_analisis": meta.get("segundos"),
    }

    if objetivo_share is not None:
        brecha = share - objetivo_share
        res["objetivo_share"] = objetivo_share
        res["brecha"] = round(brecha, 1)
        res["cumple_planograma"] = brecha >= -1.0  # 1 punto de tolerancia
        faltan = 0
        if brecha < 0 and total:
            # cuántas caras habría que sumar para llegar al objetivo
            faltan = int(np.ceil((objetivo_share / 100 * total - len(de_marca))
                                 / (1 - objetivo_share / 100))) if objetivo_share < 100 else 0
        res["caras_faltantes"] = max(0, faltan)

    alertas = []
    if vacios:
        res_baldas = [f["balda"] for f in res["baldas"] if f["vacios"]]
        alertas.append({
            "nivel": "alta",
            "texto": f"{len(vacios)} espacio(s) vacío(s) detectado(s) en la balda "
                     f"{', '.join(map(str, res_baldas))}. Posible agotado.",
        })
    if objetivo_share is not None and not res.get("cumple_planograma", True):
        alertas.append({
            "nivel": "alta",
            "texto": f"Share of shelf {res['share_of_shelf']}% contra un objetivo de "
                     f"{objetivo_share}%: faltan {res['caras_faltantes']} cara(s) para cumplir.",
        })
    if total and len(de_marca) == 0:
        alertas.append({"nivel": "media",
                        "texto": "No se marcó ningún producto de la marca auditada."})
    if not alertas:
        alertas.append({"nivel": "ok", "texto": "Góndola conforme: sin agotados y objetivo cumplido."})
    res["alertas"] = alertas
    return res


def minutos_ahorrados(facings: int) -> float:
    """Estimación conservadora del tiempo manual equivalente.

    Referencia: contar y anotar una cara en formulario toma del orden de 4 segundos
    a un mercaderista experimentado. Se compara contra eso, no contra un ideal.
    """
    return round(facings * 4 / 60, 1)

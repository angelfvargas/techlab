"""Tech Lab — laboratorio de innovación en un solo servicio local.

Arranca con:  ./.venv/bin/python -m uvicorn app:app --port 8080
y se abre en http://localhost:8080
"""
from __future__ import annotations

import csv
import io
import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from techlab import auditoria, bitacora, documentos, ficha, ia, radar, render, vision

RAIZ = Path(__file__).parent
SUBIDAS = RAIZ / "data/uploads"
SUBIDAS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Tech Lab")

# Estado en memoria de las auditorías abiertas: la foto y sus detecciones, para
# poder marcar la marca y recalcular sin volver a correr los modelos.
SESIONES: dict[str, dict] = {}


def _guardar_subida(archivo: UploadFile, prefijo: str) -> Path:
    ext = Path(archivo.filename or "").suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        raise HTTPException(400, f"Formato no soportado: {ext}")
    destino = SUBIDAS / f"{prefijo}_{uuid.uuid4().hex[:10]}{ext}"
    with destino.open("wb") as f:
        shutil.copyfileobj(archivo.file, f)
    return destino


# ------------------------------------------------------------------ general

@app.get("/", response_class=HTMLResponse)
def inicio():
    return (RAIZ / "web/index.html").read_text(encoding="utf-8")


@app.get("/api/estado")
def estado():
    return {
        "ia": ia.estado(),
        "muestras": sorted(p.name for p in (RAIZ / "data/muestras").glob("*")
                           if p.suffix.lower() in {".jpg", ".jpeg", ".png"}),
        "plantillas": {k: v["nombre"] for k, v in documentos.PLANTILLAS.items()},
        "fuentes_radar": [n for n, _ in radar.FUENTES],
    }


# ------------------------------------------------------------------ góndola

def _respuesta_gondola(sid: str) -> dict:
    s = SESIONES[sid]
    dets = s["dets"]
    ind = auditoria.indicadores(dets, s["meta"], s.get("objetivo"))
    salida = render.pintar(s["foto"], dets, str(Path(s["foto"]).with_name(
        Path(s["foto"]).stem + "_marcado.jpg")))
    s["indicadores"] = ind
    s["marcado"] = salida
    return {
        "sesion": sid,
        "detecciones": [d.dict() for d in dets],
        "meta": s["meta"],
        "indicadores": ind,
        "imagen": f"/archivo/{Path(salida).name}",
        "imagen_original": f"/archivo/{Path(s['foto']).name}",
    }


@app.post("/api/gondola/analizar")
async def gondola_analizar(
    archivo: UploadFile | None = File(None),
    muestra: str = Form(""),
    punto_venta: str = Form(""),
    objetivo: float | None = Form(None),
    sensibilidad: float = Form(0.06),
    tiling: bool = Form(True),
    ensamble: bool = Form(True),
):
    if muestra:
        origen = RAIZ / "data/muestras" / Path(muestra).name
        if not origen.exists():
            raise HTTPException(404, "Esa muestra no existe.")
        foto = SUBIDAS / f"gondola_{uuid.uuid4().hex[:10]}{origen.suffix}"
        shutil.copy(origen, foto)
    elif archivo is not None:
        foto = _guardar_subida(archivo, "gondola")
    else:
        raise HTTPException(400, "Falta la foto.")

    dets, meta = vision.detectar(str(foto), conf=sensibilidad, tiling=tiling,
                                 ensamble=ensamble)
    sid = uuid.uuid4().hex[:12]
    SESIONES[sid] = {"foto": str(foto), "dets": dets, "meta": meta,
                     "punto_venta": punto_venta, "objetivo": objetivo,
                     "parametros": {"sensibilidad": sensibilidad, "tiling": tiling,
                                    "ensamble": ensamble, "objetivo_share": objetivo}}
    return _respuesta_gondola(sid)


@app.post("/api/gondola/marca")
async def gondola_marca(cuerpo: dict):
    sid = cuerpo.get("sesion", "")
    if sid not in SESIONES:
        raise HTTPException(404, "Sesión vencida, vuelve a analizar la foto.")
    s = SESIONES[sid]
    semillas = [int(i) for i in cuerpo.get("indices", [])]
    propagar = bool(cuerpo.get("propagar", True))
    umbral = float(cuerpo.get("umbral", 0.88))

    for d in s["dets"]:
        d.marca = False
    elegidos = set(semillas)
    if propagar and semillas:
        elegidos |= set(auditoria.similares(s["foto"], s["dets"], semillas, umbral))
    for i in elegidos:
        if 0 <= i < len(s["dets"]) and s["dets"][i].tipo == "producto":
            s["dets"][i].marca = True
    s["semillas"] = semillas
    return _respuesta_gondola(sid)


@app.post("/api/gondola/objetivo")
async def gondola_objetivo(cuerpo: dict):
    sid = cuerpo.get("sesion", "")
    if sid not in SESIONES:
        raise HTTPException(404, "Sesión vencida, vuelve a analizar la foto.")
    obj = cuerpo.get("objetivo")
    SESIONES[sid]["objetivo"] = float(obj) if obj not in (None, "") else None
    SESIONES[sid]["parametros"]["objetivo_share"] = SESIONES[sid]["objetivo"]
    return _respuesta_gondola(sid)


@app.post("/api/gondola/guardar")
async def gondola_guardar(cuerpo: dict):
    sid = cuerpo.get("sesion", "")
    if sid not in SESIONES:
        raise HTTPException(404, "Sesión vencida.")
    s = SESIONES[sid]
    ind = s.get("indicadores") or auditoria.indicadores(s["dets"], s["meta"], s.get("objetivo"))
    id_ = bitacora.registrar(
        "gondola",
        cuerpo.get("titulo") or f"Auditoría {s.get('punto_venta') or 'sin punto de venta'}",
        punto_venta=cuerpo.get("punto_venta") or s.get("punto_venta", ""),
        modelo="shelf-yolov8 + yolov8s-worldv2",
        parametros=s["parametros"],
        metricas={k: v for k, v in ind.items() if k not in ("baldas", "alertas")},
        segundos=s["meta"]["segundos"],
        minutos_manual=auditoria.minutos_ahorrados(ind["facings_totales"]),
        archivo=Path(s.get("marcado", s["foto"])).name,
        notas=cuerpo.get("notas", ""))
    return {"id": id_}


@app.get("/archivo/{nombre}")
def archivo(nombre: str):
    ruta = SUBIDAS / Path(nombre).name
    if not ruta.exists():
        raise HTTPException(404, "Archivo no encontrado.")
    return FileResponse(ruta)


# --------------------------------------------------------------- documentos

@app.post("/api/documento/procesar")
async def documento_procesar(
    archivo: UploadFile | None = File(None),
    muestra: str = Form(""),
    tipo: str = Form("vinculacion"),
    usar_ia: bool = Form(True),
):
    if muestra:
        origen = RAIZ / "data/muestras" / Path(muestra).name
        if not origen.exists():
            raise HTTPException(404, "Esa muestra no existe.")
        ruta = SUBIDAS / f"doc_{uuid.uuid4().hex[:10]}{origen.suffix}"
        shutil.copy(origen, ruta)
    elif archivo is not None:
        ruta = _guardar_subida(archivo, "doc")
    else:
        raise HTTPException(400, "Falta el documento.")
    r = documentos.procesar(str(ruta), tipo, usar_ia)
    r["imagen"] = f"/archivo/{ruta.name}"
    r["archivo"] = ruta.name
    return r


@app.post("/api/documento/guardar")
async def documento_guardar(cuerpo: dict):
    campos = cuerpo.get("campos") or {}
    id_ = bitacora.registrar(
        "documento",
        cuerpo.get("titulo") or f"Documento {cuerpo.get('tipo_nombre', '')}".strip(),
        modelo=f"RapidOCR + {cuerpo.get('motor', 'reglas')}",
        parametros={"tipo": cuerpo.get("tipo"), "motor": cuerpo.get("motor")},
        metricas={"completitud": cuerpo.get("completitud"),
                  "campos": len(campos),
                  "avisos": len(cuerpo.get("avisos") or []),
                  "datos": campos},
        segundos=cuerpo.get("segundos", 0),
        # digitar un formato a mano: del orden de 25 s por campo, revisando el papel
        minutos_manual=round(len(campos) * 25 / 60, 1),
        archivo=cuerpo.get("archivo", ""),
        notas=cuerpo.get("notas", ""))
    return {"id": id_}


@app.get("/api/documento/csv")
def documento_csv():
    filas = [c for c in bitacora.corridas(500, modulo="documento")]
    datos = [dict((c.get("metricas") or {}).get("datos") or {}, id=c["id"], fecha=c["fecha"])
             for c in filas]
    columnas: list[str] = []
    for d in datos:
        for k in d:
            if k not in columnas:
                columnas.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columnas or ["id"], extrasaction="ignore")
    w.writeheader()
    for d in datos:
        w.writerow(d)
    return StreamingResponse(
        io.BytesIO(buf.getvalue().encode("utf-8-sig")), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="documentos_techlab.csv"'})


# -------------------------------------------------------------------- radar

@app.get("/api/radar")
def radar_barrido(dias: int = 7, limite: int = 30, usar_ia: bool = True):
    r = radar.barrido(dias=dias, limite=limite, usar_ia=usar_ia)
    r["id_corrida"] = bitacora.registrar(
        "radar", f"Barrido de {r['fuentes_totales']} fuentes ({dias} días)",
        modelo=("gemini" if r["motor"] == "modelo" else "reglas"),
        parametros={"dias": dias, "limite": limite},
        metricas={"publicaciones": len(r["items"]), "accionables": r["accionables"],
                  "fuentes_fallidas": len(r["fuentes_fallidas"])},
        segundos=r["segundos"],
        # revisar y clasificar a mano: del orden de 90 s por publicación
        minutos_manual=round(len(r["items"]) * 90 / 60, 1))
    return r


# ---------------------------------------------------------- bitácora y POCs

@app.get("/api/bitacora")
def api_bitacora(limite: int = 200, modulo: str | None = None):
    return {"corridas": bitacora.corridas(limite, modulo), "resumen": bitacora.resumen()}


@app.post("/api/poc/generar")
async def poc_generar(cuerpo: dict):
    ids = [int(i) for i in cuerpo.get("ids", [])]
    if not ids:
        raise HTTPException(400, "Selecciona al menos una corrida.")
    try:
        return ficha.generar(ids, cuerpo.get("usar_ia"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/poc/guardar")
async def poc_guardar(cuerpo: dict):
    return {"id": bitacora.guardar_poc(cuerpo)}


@app.get("/api/pocs")
def api_pocs():
    return {"pocs": bitacora.pocs()}


@app.delete("/api/poc/{id_}")
def poc_borrar(id_: int):
    bitacora.borrar_poc(id_)
    return {"ok": True}


@app.post("/api/poc/markdown", response_class=PlainTextResponse)
async def poc_markdown(cuerpo: dict):
    return ficha.markdown(cuerpo)


# ------------------------------------------------------------------ tablero

@app.get("/api/tablero")
def tablero():
    corridas = bitacora.corridas(500)
    gondolas = [c for c in corridas if c["modulo"] == "gondola"]
    puntos: dict[str, dict] = {}
    for c in gondolas:
        m = c.get("metricas") or {}
        p = puntos.setdefault(c["punto_venta"] or "Sin identificar",
                              {"punto_venta": c["punto_venta"] or "Sin identificar",
                               "auditorias": 0, "agotados": 0, "share": [], "facings": 0})
        p["auditorias"] += 1
        p["agotados"] += m.get("agotados", 0) or 0
        p["facings"] += m.get("facings_totales", 0) or 0
        if m.get("share_of_shelf") is not None:
            p["share"].append(m["share_of_shelf"])
    for p in puntos.values():
        p["share_promedio"] = round(sum(p["share"]) / len(p["share"]), 1) if p["share"] else None
        p.pop("share")
    serie = [{"fecha": c["fecha"][:10], "id": c["id"],
              "share": (c.get("metricas") or {}).get("share_of_shelf"),
              "agotados": (c.get("metricas") or {}).get("agotados"),
              "punto_venta": c["punto_venta"] or "Sin identificar"}
             for c in reversed(gondolas)]
    return {"resumen": bitacora.resumen(), "puntos": list(puntos.values()),
            "serie": serie, "total_auditorias": len(gondolas)}


@app.on_event("startup")
def arranque():
    # los pesos tardan en cargar: se hace al arrancar, no en la primera foto
    try:
        vision.precargar()
    except Exception as e:
        print(f"[aviso] no se pudieron precargar los modelos de visión: {e}")


app.mount("/web", StaticFiles(directory=RAIZ / "web"), name="web")

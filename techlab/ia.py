"""Cliente del modelo de lenguaje (Gemini) con degradación elegante.

Todo el módulo está escrito para que la app funcione igual sin llave: si no hay
GOOGLE_API_KEY, cada función devuelve un resultado local en vez de fallar. Eso es
deliberado — una demo no se puede caer porque se acabó la cuota.
"""
from __future__ import annotations

import base64
import json
import os
import re

import httpx

BASE = "https://generativelanguage.googleapis.com/v1beta"
MODELO = os.environ.get("TECHLAB_MODELO_IA", "gemini-2.5-flash")


def llave() -> str | None:
    return os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")


def hay_ia() -> bool:
    return bool(llave())


def estado() -> dict:
    if not hay_ia():
        return {"activa": False, "modelo": None,
                "detalle": "Sin GOOGLE_API_KEY: los módulos de IA usan el modo local."}
    try:
        r = httpx.get(f"{BASE}/models", params={"key": llave()}, timeout=15)
        r.raise_for_status()
        nombres = [m["name"].split("/")[-1] for m in r.json().get("models", [])]
        return {"activa": True, "modelo": MODELO, "disponibles": nombres[:40],
                "detalle": "Llave válida."}
    except httpx.HTTPError as e:
        return {"activa": False, "modelo": MODELO, "detalle": f"La llave falló: {e}"}


def _generar(partes: list[dict], temperatura: float = 0.2,
             json_estricto: bool = False, timeout: float = 90) -> str:
    cuerpo: dict = {
        "contents": [{"parts": partes}],
        "generationConfig": {"temperature": temperatura},
    }
    if json_estricto:
        cuerpo["generationConfig"]["responseMimeType"] = "application/json"
    r = httpx.post(f"{BASE}/models/{MODELO}:generateContent",
                   params={"key": llave()}, json=cuerpo, timeout=timeout)
    r.raise_for_status()
    datos = r.json()
    try:
        return "".join(p.get("text", "")
                       for p in datos["candidates"][0]["content"]["parts"])
    except (KeyError, IndexError):
        raise RuntimeError(f"Respuesta inesperada del modelo: {json.dumps(datos)[:300]}")


def texto(prompt: str, **kw) -> str:
    return _generar([{"text": prompt}], **kw)


def con_imagen(prompt: str, ruta_imagen: str, mime: str = "image/jpeg", **kw) -> str:
    with open(ruta_imagen, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return _generar([{"text": prompt}, {"inlineData": {"mimeType": mime, "data": b64}}], **kw)


def json_de(salida: str) -> dict | list:
    """Extrae el JSON de una respuesta, aunque venga envuelto en ```json."""
    salida = salida.strip()
    bloque = re.search(r"```(?:json)?\s*(.+?)```", salida, re.S)
    if bloque:
        salida = bloque.group(1).strip()
    try:
        return json.loads(salida)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", salida, re.S)
        if m:
            return json.loads(m.group(0))
        raise

"""Vigilancia tecnológica: qué salió esta semana y cuál de eso le sirve a Eficacia.

Un lector de noticias no aporta nada por sí solo. Lo que aporta es el filtro: cada
publicación se puntúa contra los frentes de trabajo reales del negocio (ejecución en
punto de venta, digitación de documentos, automatización de reportes, analítica) y
se propone un uso concreto. Con llave lo hace el modelo; sin llave, un puntaje por
términos que además sirve de línea base para comparar.
"""
from __future__ import annotations

import concurrent.futures
import html
import re
import time
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from . import ia

FUENTES = [
    ("arXiv · Visión por computador", "http://export.arxiv.org/rss/cs.CV"),
    ("arXiv · Inteligencia artificial", "http://export.arxiv.org/rss/cs.AI"),
    ("Google Research", "https://research.google/blog/rss/"),
    ("Hugging Face · blog", "https://huggingface.co/blog/feed.xml"),
    ("Ultralytics", "https://www.ultralytics.com/blog/rss.xml"),
    ("MIT Technology Review · IA", "https://www.technologyreview.com/topic/artificial-intelligence/feed"),
    ("The Verge · IA", "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"),
]

# Frentes de trabajo del negocio y los términos que los delatan.
FRENTES = {
    "Ejecución en punto de venta": [
        "shelf", "retail", "planogram", "product detection", "out of stock", "sku",
        "object detection", "yolo", "segmentation", "counting", "visual", "vision",
    ],
    "Digitación de documentos": [
        "ocr", "document", "handwriting", "form", "extraction", "invoice",
        "table", "parsing", "layout", "id card",
    ],
    "Automatización de procesos": [
        "agent", "browser", "playwright", "automation", "rpa", "workflow",
        "tool use", "computer use", "scraping", "orchestration",
    ],
    "Analítica y decisión": [
        "forecast", "time series", "prediction", "tabular", "recommendation",
        "clustering", "anomaly", "causal", "dashboard",
    ],
    "Modelos y costos": [
        "quantization", "distillation", "on-device", "edge", "efficient", "latency",
        "small model", "open weights", "inference", "cpu",
    ],
}

BONUS = ["open source", "open-source", "benchmark", "dataset", "release", "weights",
         "spanish", "multilingual", "free", "mobile"]


def _limpiar_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _bajar(nombre: str, url: str, dias: int) -> list[dict]:
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True,
                      headers={"User-Agent": "TechLab/1.0 (radar tecnologico)"})
        r.raise_for_status()
        feed = feedparser.parse(r.content)
    except (httpx.HTTPError, Exception):
        return []
    corte = datetime.now(timezone.utc) - timedelta(days=dias)
    items = []
    for e in feed.entries[:40]:
        fecha = None
        for campo in ("published_parsed", "updated_parsed"):
            if getattr(e, campo, None):
                fecha = datetime(*getattr(e, campo)[:6], tzinfo=timezone.utc)
                break
        if fecha and fecha < corte:
            continue
        items.append({
            "fuente": nombre,
            "titulo": _limpiar_html(getattr(e, "title", ""))[:220],
            "url": getattr(e, "link", ""),
            "resumen": _limpiar_html(getattr(e, "summary", ""))[:700],
            "fecha": fecha.date().isoformat() if fecha else "",
        })
    return items


def recolectar(dias: int = 7, limite: int = 60) -> tuple[list[dict], list[str]]:
    items: list[dict] = []
    fallidas: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as ex:
        futuros = {ex.submit(_bajar, n, u, dias): n for n, u in FUENTES}
        for f in concurrent.futures.as_completed(futuros):
            r = f.result()
            if r:
                items.extend(r)
            else:
                fallidas.append(futuros[f])
    vistos, unicos = set(), []
    for i in sorted(items, key=lambda x: x["fecha"], reverse=True):
        clave = i["titulo"].lower()[:80]
        if clave in vistos:
            continue
        vistos.add(clave)
        unicos.append(i)
    return unicos[:limite], fallidas


def _puntuar_local(item: dict) -> dict:
    texto = f"{item['titulo']} {item['resumen']}".lower()
    puntajes = {frente: sum(1 for t in terminos if t in texto)
                for frente, terminos in FRENTES.items()}
    frente, golpes = max(puntajes.items(), key=lambda kv: kv[1])
    extra = sum(1 for b in BONUS if b in texto)
    if golpes == 0:
        return {**item, "frente": "Sin encaje claro", "relevancia": 1,
                "por_que": "Ningún término de los frentes de trabajo aparece en el texto.",
                "uso": "", "motor": "reglas"}
    relevancia = min(5, 1 + golpes + min(extra, 2))
    encontrados = [t for t in FRENTES[frente] if t in texto][:4]
    return {
        **item, "frente": frente, "relevancia": relevancia,
        "por_que": "Coincide con el frente por: " + ", ".join(encontrados) + ".",
        "uso": "", "motor": "reglas",
    }


PROMPT = """Trabajas en el laboratorio de innovación de Eficacia, empresa colombiana de
trade marketing, mercaderismo y gestión humana. Sus frentes de trabajo son:
{frentes}

Te paso publicaciones técnicas recientes. Para cada una decide si sirve para alguno de
esos frentes y devuelve un arreglo JSON, un objeto por publicación EN EL MISMO ORDEN,
con estas claves:
- "frente": uno de los frentes de arriba, o "Sin encaje claro".
- "relevancia": entero de 1 a 5 (5 = aplicable ya a un proceso de la empresa).
- "por_que": una frase corta, en español, de por qué sí o por qué no.
- "uso": si la relevancia es 3 o más, una frase con el uso concreto en la operación
  (ej. "medir share of shelf sin conexión desde el celular del mercaderista").
  Si es menor a 3, cadena vacía.

Sé estricto: la mayoría de publicaciones de investigación NO son aplicables todavía.

Publicaciones:
{lista}"""


def analizar(items: list[dict], usar_ia: bool | None = None) -> tuple[list[dict], str, str | None]:
    usar_ia = ia.hay_ia() if usar_ia is None else (usar_ia and ia.hay_ia())
    if not usar_ia or not items:
        return [_puntuar_local(i) for i in items], "reglas", None
    lista = "\n".join(f'{n+1}. "{i["titulo"]}" — {i["resumen"][:280]}'
                      for n, i in enumerate(items))
    try:
        salida = ia.texto(
            PROMPT.format(frentes="\n".join(f"- {f}" for f in FRENTES), lista=lista),
            json_estricto=True, timeout=180)
        datos = ia.json_de(salida)
        if not isinstance(datos, list) or len(datos) != len(items):
            raise ValueError(f"El modelo devolvió {len(datos) if isinstance(datos, list) else '?'} "
                             f"análisis para {len(items)} publicaciones.")
        salida_final = []
        for item, a in zip(items, datos):
            salida_final.append({
                **item,
                "frente": a.get("frente", "Sin encaje claro"),
                "relevancia": int(a.get("relevancia", 1)),
                "por_que": a.get("por_que", ""),
                "uso": a.get("uso", ""),
                "motor": "modelo",
            })
        return salida_final, "modelo", None
    except Exception as e:
        return [_puntuar_local(i) for i in items], "reglas", f"{type(e).__name__}: {e}"


def barrido(dias: int = 7, limite: int = 40, usar_ia: bool | None = None) -> dict:
    t0 = time.time()
    items, fallidas = recolectar(dias, limite)
    analizados, motor, error = analizar(items, usar_ia)
    analizados.sort(key=lambda x: (-x["relevancia"], x["fuente"]))
    return {
        "items": analizados,
        "motor": motor,
        "error_ia": error,
        "fuentes_totales": len(FUENTES),
        "fuentes_fallidas": fallidas,
        "dias": dias,
        "segundos": round(time.time() - t0, 2),
        "accionables": sum(1 for i in analizados if i["relevancia"] >= 4),
    }

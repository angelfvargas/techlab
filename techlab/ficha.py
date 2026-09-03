"""Generación de la ficha de un POC a partir de las corridas registradas.

La documentación es lo primero que se deja de hacer en un laboratorio. Aquí no se
escribe a mano: se toman las corridas reales de la bitácora, con sus parámetros y
métricas, y de ahí sale la ficha en formato hipótesis / método / resultado /
conclusión. Con llave la redacta el modelo; sin llave, una plantilla que arma las
mismas secciones con los números.
"""
from __future__ import annotations

import json
import statistics

from . import bitacora, ia

NOMBRES = {
    "gondola": "auditoría de góndola por visión computacional",
    "documento": "extracción de datos de documentos",
    "radar": "vigilancia tecnológica",
}


def _contexto(ids: list[int]) -> tuple[list[dict], dict]:
    corridas = [c for c in (bitacora.corrida(i) for i in ids) if c]
    if not corridas:
        return [], {}
    modulos = {c["modulo"] for c in corridas}
    tiempos = [c["segundos"] for c in corridas if c["segundos"]]
    agregado = {
        "n_corridas": len(corridas),
        "modulos": sorted(modulos),
        "segundos_promedio": round(statistics.mean(tiempos), 2) if tiempos else 0,
        "segundos_max": round(max(tiempos), 2) if tiempos else 0,
        "minutos_manual": round(sum(c["minutos_manual"] or 0 for c in corridas), 1),
        "minutos_maquina": round(sum(tiempos) / 60, 2) if tiempos else 0,
    }
    return corridas, agregado


PROMPT = """Redacta la ficha técnica de una prueba de concepto (POC) del laboratorio de
innovación de Eficacia, empresa colombiana de trade marketing y gestión humana.

Escribe en español de Colombia, en tono técnico y sobrio, sin adjetivos de marketing y
sin exagerar los resultados. Si los datos no alcanzan para afirmar algo, dilo.

Datos reales de las corridas ejecutadas:
{datos}

Resumen agregado:
{agregado}

Devuelve SOLO un objeto JSON con estas claves, cada una en texto plano:
- "titulo": título corto de la POC.
- "hipotesis": qué se quería comprobar, una o dos frases.
- "metodo": qué se hizo, con los modelos y parámetros que aparecen en los datos.
- "resultado": los números observados, citándolos. Nada que no esté en los datos.
- "conclusion": si sirve o no para la operación, qué falta para llevarlo a producción,
  y los riesgos o límites que se vieron.
- "estado": uno de "viable", "requiere ajustes", "descartado"."""


def _por_plantilla(corridas: list[dict], ag: dict) -> dict:
    modulos = ", ".join(NOMBRES.get(m, m) for m in ag["modulos"])
    lineas_res = []
    for c in corridas:
        met = c.get("metricas") or {}
        resumen = ", ".join(f"{k}={v}" for k, v in met.items()
                            if isinstance(v, (int, float, str)))[:300]
        lineas_res.append(f"- Corrida #{c['id']} ({c['titulo']}): {resumen or 'sin métricas'} "
                          f"[{c['segundos']} s]")
    ahorro = round(ag["minutos_manual"] - ag["minutos_maquina"], 1)
    return {
        "titulo": f"POC de {modulos}",
        "hipotesis": f"Comprobar si {modulos} puede ejecutarse con la calidad y el tiempo "
                     f"que exige la operación, sobre equipos y datos propios.",
        "metodo": f"Se ejecutaron {ag['n_corridas']} corrida(s) sobre casos reales. "
                  f"Modelos y parámetros usados: "
                  + "; ".join(f"#{c['id']} {c['modelo']} {json.dumps(c.get('parametros') or {}, ensure_ascii=False)}"
                              for c in corridas)[:900] + ".",
        "resultado": "\n".join(lineas_res)
                     + f"\nTiempo promedio por corrida: {ag['segundos_promedio']} s "
                       f"(máximo {ag['segundos_max']} s). Equivalente manual estimado: "
                       f"{ag['minutos_manual']} min contra {ag['minutos_maquina']} min de máquina.",
        "conclusion": (f"El ahorro estimado frente al proceso manual es de {ahorro} min "
                       f"en esta muestra. La muestra es pequeña, así que el dato sirve para "
                       f"decidir si se sigue, no para proyectar a toda la operación. "
                       f"Antes de producción falta validar con fotos y documentos propios de "
                       f"la empresa y medir el error contra un conteo hecho a mano."),
        "estado": "requiere ajustes",
        "motor": "plantilla",
    }


def generar(ids: list[int], usar_ia: bool | None = None) -> dict:
    corridas, ag = _contexto(ids)
    if not corridas:
        raise ValueError("No hay corridas con esos identificadores.")
    usar_ia = ia.hay_ia() if usar_ia is None else (usar_ia and ia.hay_ia())
    if usar_ia:
        datos = json.dumps([{k: c[k] for k in
                             ("id", "modulo", "titulo", "punto_venta", "modelo",
                              "parametros", "metricas", "segundos", "minutos_manual")}
                            for c in corridas], ensure_ascii=False, indent=1)[:14000]
        try:
            salida = ia.texto(PROMPT.format(datos=datos,
                                            agregado=json.dumps(ag, ensure_ascii=False)),
                              temperatura=0.3, json_estricto=True, timeout=120)
            d = ia.json_de(salida)
            if isinstance(d, dict) and d.get("resultado"):
                return {**d, "motor": "modelo", "corridas": ids, "agregado": ag}
        except Exception as e:
            base = _por_plantilla(corridas, ag)
            return {**base, "corridas": ids, "agregado": ag,
                    "error_ia": f"{type(e).__name__}: {e}"}
    return {**_por_plantilla(corridas, ag), "corridas": ids, "agregado": ag}


def markdown(poc: dict) -> str:
    ag = poc.get("agregado") or {}
    return f"""# {poc.get('titulo', 'POC')}

**Estado:** {poc.get('estado', '-')}  ·  **Corridas:** {', '.join('#' + str(i) for i in poc.get('corridas', []))}  ·  **Generado por:** {poc.get('motor', '-')}

## Hipótesis
{poc.get('hipotesis', '')}

## Método
{poc.get('metodo', '')}

## Resultado
{poc.get('resultado', '')}

## Conclusión
{poc.get('conclusion', '')}

---
*Ficha generada automáticamente por Tech Lab a partir de {ag.get('n_corridas', 0)} corrida(s) registrada(s) en la bitácora.*
"""

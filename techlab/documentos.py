"""Lectura de documentos de vinculación: de la foto a campos estructurados.

Contratar en masa significa digitar el mismo formato miles de veces. Aquí el OCR
corre siempre local (RapidOCR, sin internet ni llaves) y de ahí salen los campos:
con el modelo de lenguaje si hay llave, y con reglas si no la hay. Las dos rutas
producen el mismo formato de salida, así que la app se ve igual en cualquier caso.
"""
from __future__ import annotations

import re
import time
from datetime import date

from . import ia

_ocr = None

# Plantillas: qué campos se esperan según el tipo de documento.
PLANTILLAS: dict[str, dict] = {
    "vinculacion": {
        "nombre": "Formato de vinculación",
        "campos": ["nombre_completo", "numero_documento", "telefono", "correo",
                   "direccion", "ciudad", "eps", "fondo_pension", "cargo",
                   "fecha_ingreso"],
    },
    "cedula": {
        "nombre": "Cédula de ciudadanía",
        "campos": ["numero_documento", "primer_apellido", "segundo_apellido",
                   "nombres", "fecha_nacimiento", "lugar_nacimiento", "sexo",
                   "fecha_expedicion", "lugar_expedicion"],
    },
    "certificado_estudio": {
        "nombre": "Certificado de estudio",
        "campos": ["nombre_completo", "numero_documento", "institucion",
                   "programa", "semestre", "fecha_expedicion"],
    },
    "rut": {
        "nombre": "RUT",
        "campos": ["razon_social", "nit", "digito_verificacion", "direccion",
                   "ciudad", "actividad_economica"],
    },
}


def motor_ocr():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr = RapidOCR()
    return _ocr


def leer_texto(ruta: str) -> tuple[str, list[dict], float]:
    """OCR local. Devuelve el texto plano, las líneas con su caja y la confianza media."""
    t0 = time.time()
    resultado, _ = motor_ocr()(ruta)
    lineas = []
    for caja, txt, conf in (resultado or []):
        xs = [p[0] for p in caja]
        ys = [p[1] for p in caja]
        lineas.append({"texto": txt, "conf": round(float(conf), 3),
                       "x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)})
    texto = "\n".join(l["texto"] for l in lineas)
    conf_media = round(sum(l["conf"] for l in lineas) / len(lineas), 3) if lineas else 0.0
    return texto, lineas, round(time.time() - t0, 2)


# ------------------------------------------------------------ modo sin llave

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
         "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
         "noviembre": 11, "diciembre": 12}


def _normalizar_numero(s: str) -> str:
    return re.sub(r"[^\d]", "", s)


def _filas_visuales(lineas: list[dict]) -> list[str]:
    """Une en una sola línea los recuadros de OCR que están a la misma altura.

    En un formato la etiqueta y el valor son dos recuadros distintos de la misma
    fila; sin volverlos a juntar, la regla 'Etiqueta: valor' nunca coincide.
    """
    if not lineas:
        return []
    orden = sorted(lineas, key=lambda l: (l["y1"], l["x1"]))
    filas: list[list[dict]] = [[orden[0]]]
    for l in orden[1:]:
        ref = filas[-1][-1]
        alto = max(1.0, min(ref["y2"] - ref["y1"], l["y2"] - l["y1"]))
        solape = min(ref["y2"], l["y2"]) - max(ref["y1"], l["y1"])
        if solape > alto * 0.5:
            filas[-1].append(l)
        else:
            filas.append([l])
    salida = []
    for fila in filas:
        partes = [c["texto"].strip() for c in sorted(fila, key=lambda c: c["x1"])]
        texto = partes[0]
        for p in partes[1:]:
            texto += ("" if texto.endswith(":") else ":") + " " + p if ":" not in texto else " " + p
        salida.append(texto)
    return salida


def _por_reglas(texto: str, tipo: str, lineas: list[dict] | None = None) -> dict:
    """Extracción sin modelo: etiqueta-valor y patrones colombianos.

    No pretende igualar al modelo; existe para que la app siga siendo útil sin
    llave y para poder comparar las dos rutas en la bitácora.
    """
    campos: dict[str, str] = {}
    filas = _filas_visuales(lineas) if lineas else []
    lineas_txt = filas or [l.strip() for l in texto.splitlines() if l.strip()]

    # 1) Pares "Etiqueta: valor" en la misma fila, o etiqueta sola y valor debajo.
    alias = {
        "primer_apellido": r"primer\s+apellido",
        "segundo_apellido": r"segundo\s+apellido",
        "fecha_nacimiento": r"fecha\s+de\s+nacimiento",
        "lugar_nacimiento": r"lugar\s+de\s+nacimiento",
        "fecha_expedicion": r"(fecha\s+de\s+expedici[oó]n|expedida)",
        "lugar_expedicion": r"lugar\s+de\s+expedici[oó]n",
        "fecha_ingreso": r"fecha\s+de\s+ingreso",
        "fondo_pension": r"(fondo\s+de\s+pensi[oó]n|fondo\s+de\s+pensiones|pensi[oó]n|afp)",
        "numero_documento": r"(n[uú]mero\s+de\s+documento|c[eé]dula|documento|identificaci[oó]n|c\.?\s?c\.?)",
        "digito_verificacion": r"(d[ií]gito\s+de\s+verificaci[oó]n|dv)",
        "razon_social": r"raz[oó]n\s+social",
        "nombre_completo": r"(nombre\s+completo|nombres?\s+y\s+apellidos?|nombre)",
        "nombres": r"nombres?",
        "telefono": r"(tel[eé]fono|celular|contacto)",
        "correo": r"(correo|e-?mail)",
        "direccion": r"direcci[oó]n",
        "ciudad": r"(ciudad|municipio)",
        "eps": r"eps",
        "cargo": r"cargo",
        "institucion": r"(instituci[oó]n|universidad|colegio)",
        "programa": r"(programa|carrera)",
        "semestre": r"semestre",
        "nit": r"nit",
        "sexo": r"(sexo|g[eé]nero)",
        "actividad_economica": r"actividad\s+econ[oó]mica",
    }
    esperados = PLANTILLAS.get(tipo, {}).get("campos", list(alias))
    # Se recorren los alias en orden: los más específicos primero, para que
    # "fecha de expedición" no se lo lleve el alias genérico "documento".
    for i, linea in enumerate(lineas_txt):
        etiqueta, _, valor = linea.partition(":")
        if not _:
            continue
        etiqueta = etiqueta.strip()
        for campo in alias:
            if campo in campos or campo not in esperados:
                continue
            if re.fullmatch(rf"\W*{alias[campo]}\W*", etiqueta, re.I):
                v = valor.strip()
                if not v and i + 1 < len(lineas_txt) and ":" not in lineas_txt[i + 1]:
                    v = lineas_txt[i + 1].strip()
                if v:
                    campos[campo] = v
                break

    # 2) Patrones que no necesitan etiqueta.
    if "correo" in esperados and "correo" not in campos:
        m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", texto)
        if m:
            campos["correo"] = m.group(0)
    if "telefono" in esperados and "telefono" not in campos:
        m = re.search(r"\b3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b", texto)
        if m:
            campos["telefono"] = _normalizar_numero(m.group(0))
    if "numero_documento" in esperados and "numero_documento" not in campos:
        # cédulas colombianas: 6 a 10 dígitos, normalmente con puntos de miles
        m = re.search(r"\b\d{1,3}(?:[.\s]\d{3}){1,3}\b|\b\d{7,10}\b", texto)
        if m:
            campos["numero_documento"] = _normalizar_numero(m.group(0))

    for campo, valor in list(campos.items()):
        campos[campo] = _limpiar(campo, valor)
    return campos


def _limpiar(campo: str, valor: str) -> str:
    if campo in ("numero_documento", "nit", "telefono"):
        return _normalizar_numero(valor) or valor
    if campo.startswith("fecha"):
        v = valor.lower()
        m = re.search(r"(\d{1,2})\s*(?:de)?\s*([a-záéíóú]+)\s*(?:de)?\s*(\d{4})", v)
        if m and m.group(2) in MESES:
            return f"{m.group(3)}-{MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", v)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", v)
        if m:
            return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return valor.strip()


# ------------------------------------------------------------ validaciones

def dv_nit(nit: str) -> int | None:
    """Dígito de verificación del NIT según la fórmula de la DIAN."""
    n = _normalizar_numero(nit)
    if not n:
        return None
    pesos = [3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71]
    suma = sum(int(d) * pesos[i] for i, d in enumerate(reversed(n)) if i < len(pesos))
    r = suma % 11
    return r if r < 2 else 11 - r


def validar(campos: dict) -> list[dict]:
    avisos = []
    doc = _normalizar_numero(campos.get("numero_documento", ""))
    if campos.get("numero_documento") and not 6 <= len(doc) <= 10:
        avisos.append({"campo": "numero_documento", "nivel": "error",
                       "texto": f"'{campos['numero_documento']}' no tiene entre 6 y 10 dígitos."})
    tel = _normalizar_numero(campos.get("telefono", ""))
    if campos.get("telefono") and not (len(tel) == 10 and tel.startswith("3")) and len(tel) != 7:
        avisos.append({"campo": "telefono", "nivel": "aviso",
                       "texto": "El teléfono no parece un celular colombiano (10 dígitos, empieza en 3)."})
    if campos.get("correo") and not re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.]+", campos["correo"].strip()):
        avisos.append({"campo": "correo", "nivel": "error", "texto": "Correo mal formado."})
    if campos.get("nit") and campos.get("digito_verificacion"):
        esperado = dv_nit(campos["nit"])
        dado = _normalizar_numero(str(campos["digito_verificacion"]))
        if dado and esperado is not None and int(dado) != esperado:
            avisos.append({"campo": "digito_verificacion", "nivel": "error",
                           "texto": f"El DV del NIT debería ser {esperado}, no {dado}."})
    fn = campos.get("fecha_nacimiento", "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", fn or "")
    if m:
        edad = (date.today() - date(int(m.group(1)), int(m.group(2)), int(m.group(3)))).days // 365
        if edad < 18:
            avisos.append({"campo": "fecha_nacimiento", "nivel": "error",
                           "texto": f"La persona tendría {edad} años: menor de edad."})
        elif edad > 90:
            avisos.append({"campo": "fecha_nacimiento", "nivel": "aviso",
                           "texto": "Fecha de nacimiento poco probable, revisar el OCR."})
    faltantes = [c for c in campos if not str(campos.get(c) or "").strip()]
    for c in faltantes:
        avisos.append({"campo": c, "nivel": "aviso", "texto": "Campo vacío, revisar a mano."})
    return avisos


# ------------------------------------------------------------ orquestación

PROMPT = """Eres un asistente de digitación de una empresa colombiana de gestión humana.
Del texto de un documento escaneado extrae exactamente estos campos: {campos}.

Reglas:
- Devuelve SOLO un objeto JSON con esas claves, sin explicaciones.
- Si un campo no aparece en el texto, deja la cadena vacía "".
- Los números de documento van sin puntos ni espacios.
- Las fechas van en formato AAAA-MM-DD.
- No inventes datos que no estén en el texto.

Texto del documento:
---
{texto}
---"""


def procesar(ruta: str, tipo: str = "vinculacion", usar_ia: bool | None = None) -> dict:
    t0 = time.time()
    texto, lineas, seg_ocr = leer_texto(ruta)
    plantilla = PLANTILLAS.get(tipo, PLANTILLAS["vinculacion"])
    esperados = plantilla["campos"]
    usar_ia = ia.hay_ia() if usar_ia is None else (usar_ia and ia.hay_ia())

    motor, error = "reglas", None
    campos = {c: "" for c in esperados}
    if usar_ia:
        try:
            salida = ia.texto(PROMPT.format(campos=", ".join(esperados), texto=texto[:12000]),
                              json_estricto=True)
            datos = ia.json_de(salida)
            if isinstance(datos, dict):
                campos.update({c: _limpiar(c, str(datos.get(c, "") or "")) for c in esperados})
                motor = "modelo"
        except Exception as e:  # una demo no se cae porque falle la nube
            error = f"{type(e).__name__}: {e}"
    if motor == "reglas":
        campos.update(_por_reglas(texto, tipo, lineas))
        campos = {c: campos.get(c, "") for c in esperados}

    return {
        "tipo": tipo,
        "tipo_nombre": plantilla["nombre"],
        "motor": motor,
        "error_ia": error,
        "campos": campos,
        "avisos": validar(campos),
        "texto_ocr": texto,
        "lineas": lineas,
        "segundos_ocr": seg_ocr,
        "segundos": round(time.time() - t0, 2),
        "completitud": round(
            sum(1 for c in esperados if str(campos.get(c) or "").strip()) / len(esperados) * 100, 1),
    }

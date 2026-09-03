"""Bitácora de experimentos: qué se probó, con qué, y qué salió.

Es el registro que pide la responsabilidad de gestión del conocimiento: cada corrida
de cualquier módulo queda guardada con sus parámetros y sus métricas, y de ahí se
genera sola la ficha del POC.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RUTA = Path("data/techlab.db")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS corridas (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha         TEXT NOT NULL,
  modulo        TEXT NOT NULL,
  titulo        TEXT NOT NULL,
  punto_venta   TEXT,
  modelo        TEXT,
  parametros    TEXT,
  metricas      TEXT,
  segundos      REAL,
  minutos_manual REAL,
  archivo       TEXT,
  notas         TEXT
);
CREATE TABLE IF NOT EXISTS pocs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  fecha      TEXT NOT NULL,
  titulo     TEXT NOT NULL,
  hipotesis  TEXT,
  metodo     TEXT,
  resultado  TEXT,
  conclusion TEXT,
  estado     TEXT,
  corridas   TEXT
);
"""


def conexion() -> sqlite3.Connection:
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RUTA)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def ahora() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def registrar(modulo: str, titulo: str, *, punto_venta: str = "", modelo: str = "",
              parametros: dict | None = None, metricas: dict | None = None,
              segundos: float = 0, minutos_manual: float = 0,
              archivo: str = "", notas: str = "") -> int:
    con = conexion()
    cur = con.execute(
        "INSERT INTO corridas (fecha, modulo, titulo, punto_venta, modelo, parametros,"
        " metricas, segundos, minutos_manual, archivo, notas)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ahora(), modulo, titulo, punto_venta, modelo,
         json.dumps(parametros or {}, ensure_ascii=False),
         json.dumps(metricas or {}, ensure_ascii=False),
         segundos, minutos_manual, archivo, notas))
    con.commit()
    id_ = cur.lastrowid
    con.close()
    return id_


def _fila(r: sqlite3.Row) -> dict:
    d = dict(r)
    for campo in ("parametros", "metricas", "corridas"):
        if campo in d and d[campo]:
            try:
                d[campo] = json.loads(d[campo])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def corridas(limite: int = 200, modulo: str | None = None) -> list[dict]:
    con = conexion()
    if modulo:
        cur = con.execute("SELECT * FROM corridas WHERE modulo=? ORDER BY id DESC LIMIT ?",
                          (modulo, limite))
    else:
        cur = con.execute("SELECT * FROM corridas ORDER BY id DESC LIMIT ?", (limite,))
    filas = [_fila(r) for r in cur.fetchall()]
    con.close()
    return filas


def corrida(id_: int) -> dict | None:
    con = conexion()
    r = con.execute("SELECT * FROM corridas WHERE id=?", (id_,)).fetchone()
    con.close()
    return _fila(r) if r else None


def resumen() -> dict:
    con = conexion()
    r = con.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(segundos),0) s, COALESCE(SUM(minutos_manual),0) m"
        " FROM corridas").fetchone()
    por_modulo = con.execute(
        "SELECT modulo, COUNT(*) n FROM corridas GROUP BY modulo").fetchall()
    n_pocs = con.execute("SELECT COUNT(*) n FROM pocs").fetchone()["n"]
    con.close()
    minutos_maquina = r["s"] / 60
    return {
        "corridas": r["n"],
        "minutos_manual": round(r["m"], 1),
        "minutos_maquina": round(minutos_maquina, 1),
        "minutos_ahorrados": round(max(0.0, r["m"] - minutos_maquina), 1),
        "por_modulo": {x["modulo"]: x["n"] for x in por_modulo},
        "pocs": n_pocs,
    }


def guardar_poc(datos: dict) -> int:
    con = conexion()
    cur = con.execute(
        "INSERT INTO pocs (fecha, titulo, hipotesis, metodo, resultado, conclusion,"
        " estado, corridas) VALUES (?,?,?,?,?,?,?,?)",
        (ahora(), datos.get("titulo", "POC sin título"), datos.get("hipotesis", ""),
         datos.get("metodo", ""), datos.get("resultado", ""), datos.get("conclusion", ""),
         datos.get("estado", "en curso"),
         json.dumps(datos.get("corridas", []), ensure_ascii=False)))
    con.commit()
    id_ = cur.lastrowid
    con.close()
    return id_


def pocs() -> list[dict]:
    con = conexion()
    filas = [_fila(r) for r in con.execute("SELECT * FROM pocs ORDER BY id DESC").fetchall()]
    con.close()
    return filas


def borrar_poc(id_: int) -> None:
    con = conexion()
    con.execute("DELETE FROM pocs WHERE id=?", (id_,))
    con.commit()
    con.close()

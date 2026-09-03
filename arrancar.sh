#!/usr/bin/env bash
# Arranca Tech Lab y abre el navegador. Ctrl+C para apagarlo.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "No existe .venv. Ejecuta primero:  python3 -m venv .venv && ./.venv/bin/pip install -r requisitos.txt"
  exit 1
fi

PUERTO=${PUERTO:-8080}
echo "Tech Lab arrancando en http://localhost:$PUERTO"
echo "La primera vez tarda ~20 s cargando los modelos de visión."
echo

( sleep 12; command -v google-chrome >/dev/null && google-chrome "http://localhost:$PUERTO" >/dev/null 2>&1 || true ) &

exec ./.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$PUERTO"

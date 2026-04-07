#!/bin/bash
# Rode no servidor Ubuntu (na pasta do projeto) para subir o app com Gunicorn + gevent.
# Uso: ./run_gunicorn.sh   ou   bash run_gunicorn.sh

set -e
cd "$(dirname "$0")"

# Se existir venv, ativa
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Gunicorn com worker que suporta WebSocket (evita "Invalid websocket upgrade")
exec python3 -m gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --timeout 120 --bind 0.0.0.0:5000 app:app

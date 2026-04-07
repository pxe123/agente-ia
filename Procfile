# Worker gevent + 1 processo: Socket.IO (polling/ws) precisa de sessão no mesmo worker.
# Aumentar -w sem Redis + sticky sessions devolve 400 nos POST /socket.io/.
# Na VPS pode usar run_gunicorn.sh (porta 5000) em vez disto.
web: /bin/sh -c 'exec gunicorn -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker -w 1 --timeout 120 --bind 0.0.0.0:${PORT:-5000} app:app'

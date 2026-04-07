# Systemd `agente-ia.service` (Socket.IO sem erro 400)

O `deploy.ps1` **não** altera o ficheiro do systemd. Se o serviço ainda usa `gunicorn app:app` (worker sync) ou **vários** workers (`-w 2`…), o Socket.IO continua a devolver **400** nos POST `/socket.io/`.

## 1. Ver o que está a correr hoje

No servidor:

```bash
sudo systemctl cat agente-ia
```

Repara na linha `ExecStart`. Tem de incluir **tudo** isto:

- `-k geventwebsocket.gunicorn.workers.GeventWebSocketWorker`
- `-w 1` (um único worker)
- `--timeout 120`

## 2. Exemplo de unit (ajusta caminhos ao teu utilizador e pasta)

Caminho típico: `/home/ubuntu/agente-ia` e venv em `~/agente-ia/venv`.

```ini
[Unit]
Description=Agente IA (Flask + Socket.IO)
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/agente-ia
Environment=PATH=/home/ubuntu/agente-ia/venv/bin:/usr/bin
EnvironmentFile=-/home/ubuntu/agente-ia/.env
ExecStart=/home/ubuntu/agente-ia/venv/bin/python -m gunicorn \
  -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker \
  -w 1 \
  --timeout 120 \
  --bind 127.0.0.1:5000 \
  app:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

- Se **não** usas venv, troca `ExecStart` por algo como:  
  `ExecStart=/usr/bin/python3 -m gunicorn ...`  
  (desde que `gevent`, `gevent-websocket` e `gunicorn` estejam instalados para esse Python.)
- Se o Nginx faz `proxy_pass` para `127.0.0.1:5000`, **`--bind 127.0.0.1:5000`** é adequado. Se acederes ao Flask sem Nginx na mesma máquina, podes usar `0.0.0.0:5000`.
- `EnvironmentFile=-/home/ubuntu/agente-ia/.env` é opcional (o `-` ignora se o ficheiro não existir). Muitas instalações já carregam o `.env` pela app; se o teu serviço já define variáveis, podes omitir esta linha.

## 3. Aplicar

```bash
sudo nano /etc/systemd/system/agente-ia.service
# colar / ajustar ExecStart
sudo systemctl daemon-reload
sudo systemctl restart agente-ia
sudo systemctl status agente-ia
```

## 4. Nginx

Confirma que tens o bloco `location /socket.io/` descrito em `DOMAIN_ROUTING.md` (timeouts longos, `proxy_buffering off`, headers WebSocket).

## 5. Variáveis no `.env` do servidor

Para CORS do Socket.IO em produção:

```env
PRODUCTION=1
# Defaults no código: propaganda ZapAction + app na API (podes omitir se coincidirem):
# PUBLIC_BASE_URL=https://zapaction.com.br
# APP_BASE_URL=https://api.updigitalbrasil.com.br
```

Se usares **`CORS_ORIGINS`** sem o `Origin` real (ZapAction ou API), o Socket.IO pode recusar — alinha `CORS_ORIGINS` ou mantém **`PUBLIC_BASE_URL`** / **`APP_BASE_URL`** (o `app.py` junta-as às origens permitidas).

# Domain Routing (Publico x App)

## Modelo ZapAction (propaganda + app)

- **ZapAction** (`zapaction.com.br` / `www.zapaction.com.br`) — **propaganda** (`/`, `/precos`, `/cadastro`, legais, landing, estáticos) **e** **`/login`** / **`/nova-senha`**. O formulário de login (JS) chama a API em `APP_BASE_URL` com `credentials` para gravar a sessão no domínio da app; depois o browser abre o painel na API.
- **API** (`api.updigitalbrasil.com.br`) — painel, chat, Socket.IO, `/auth/*` (POST do login), `/api/`, `/admin`, `/meta`, `/flow`, webhooks, etc.

No código, os defaults em `base/domain_redirects.py` são exatamente estes dois hosts. No `.env` podes sobrescrever com **`PUBLIC_BASE_URL`** e **`APP_BASE_URL`**.

O Flask usa **301/308** quando a rota não combina com o host (ex.: `zapaction.com.br/painel` → API; `api.../precos`, `api.../login` ou `api.../nova-senha` → `PUBLIC_BASE_URL`). **www** e apex do público contam como o mesmo site. Com dois domínios em produção, o cookie de sessão usa **SameSite=None** + **Secure** para o login por XHR entre ZapAction e API.

## Um só domínio (exceção)

Se quiseres marketing e app no **mesmo** host, define **`PUBLIC_BASE_URL`** e **`APP_BASE_URL`** com o **mesmo** URL no `.env` — os redirecionamentos entre hosts desativam-se.

## Nginx (exemplo)

```nginx
server {
    listen 80;
    server_name zapaction.com.br www.zapaction.com.br;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name zapaction.com.br www.zapaction.com.br;

    # ... ssl_certificate / ssl_certificate_key ...

    # Socket.IO: antes do location / — evita 400 em polling (buffer/timeouts) e permite WebSocket.
    location /socket.io/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

server {
    listen 80;
    server_name api.updigitalbrasil.com.br;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.updigitalbrasil.com.br;

    # ... ssl_certificate / ssl_certificate_key ...

    location /socket.io/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }

    # Rotas de app/API/socket seguem no dominio api
    location ~ ^/(api/|admin|chat|painel|meta|webhook/|sw.js|static/) {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Fallback: qualquer rota publica acessada no api redireciona para o dominio publico
    location = / { return 301 https://zapaction.com.br/; }
    location = /precos { return 301 https://zapaction.com.br/precos; }
    location = /cadastro { return 301 https://zapaction.com.br/cadastro; }
    location = /assinatura { return 301 https://zapaction.com.br/assinatura; }
    location = /politica { return 301 https://zapaction.com.br/politica; }
    location = /termos { return 301 https://zapaction.com.br/termos; }
    location = /exclusao-de-dados { return 301 https://zapaction.com.br/exclusao-de-dados; }

    # Demais rotas: app
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

## Variaveis de ambiente recomendadas

Exemplo **produção** (ZapAction + API Up Digital; login no ZapAction chama `POST /auth/*` na API):

```env
PRODUCTION=1

# Canónicas (podes omitir se forem exactamente os defaults do código)
PUBLIC_BASE_URL=https://zapaction.com.br
APP_BASE_URL=https://api.updigitalbrasil.com.br

# CORS: TODAS as origens de onde o browser chama a API com fetch/XHR.
# Obrigatório incluir o site de propaganda (login no ZapAction) + cada host da API que uses.
# Sem https://zapaction.com.br aqui, o login por JS a partir do ZapAction falha no preflight.
CORS_ORIGINS=https://zapaction.com.br,https://www.zapaction.com.br,https://api.updigitalbrasil.com.br,https://api.updigital.com.br
```

- **`CORS_ORIGINS` vazio**: o Flask não aplica `CORS(app, r/*)` restritivo; `/auth/*` continua com origens calculadas (público + app) e o Socket.IO usa `PUBLIC_BASE_URL` + `APP_BASE_URL` no `_socketio_cors_allowed_origins`.
- **`CORS_ORIGINS` preenchido**: lista **tem** de incluir **ZapAction** (com e sem `www` se usares os dois) **e** cada URL da API que apareça no browser. Só `https://api...` não basta para o login no domínio público.

Se um dia usares **um único domínio** para tudo, define `PUBLIC_BASE_URL` e `APP_BASE_URL` **iguais** e `CORS_ORIGINS` só com esse origin (ou vazio).

Observacao: com dois domínios, o Flask envia rotas de marketing (e `/login`) pedidas na API para `PUBLIC_BASE_URL`.

## Socket.IO (erro 400 em `/socket.io/`)

1. Gunicorn com **um** worker **gevent** (`GeventWebSocketWorker`), nunca vários workers sem Redis + sticky sessions.
2. Nginx: bloco `location /socket.io/` acima (timeouts longos, `proxy_buffering off`, headers WebSocket).
3. Depois de editar o Nginx: `sudo nginx -t && sudo systemctl reload nginx`.

# Domain Routing (Publico x App)

Objetivo: no mesmo servidor, separar host publico e host do app/API.

- Publico: `zapaction.com.br` (+ `www.zapaction.com.br`)
- App/API: `api.updigitalbrasil.com.br`

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

    # Rotas de app/API/socket seguem no dominio api
    location ~ ^/(api/|admin|chat|painel|meta|socket.io|webhook/|sw.js|static/) {
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

```env
PUBLIC_BASE_URL=https://zapaction.com.br
APP_BASE_URL=https://api.updigitalbrasil.com.br
```

Observacao: o Flask ja contem fallback de redirect para rotas publicas quando o host for `api.updigitalbrasil.com.br`.

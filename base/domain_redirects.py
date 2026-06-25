"""
Domínio de propaganda (público) vs domínio da app (API / painel).

Por defeito (sem .env): site público em ZapAction; app em api.updigitalbrasil.com.br.
Para servir tudo num único domínio: defina PUBLIC_BASE_URL e APP_BASE_URL com o mesmo URL.
"""
import os
from urllib.parse import quote, urlparse

# Canónico de marketing (propaganda). Sobrescreve com PUBLIC_BASE_URL no .env.
DEFAULT_PUBLIC_MARKETING_BASE = "https://zapaction.com.br"
# App: login, painel, Socket.IO, APIs. Sobrescreve com APP_BASE_URL no .env.
DEFAULT_APP_BASE = "https://api.updigitalbrasil.com.br"

# Páginas só no host de propaganda (marketing). Em ambientes com dois domínios,
# manter o login no host da app evita bloqueio de cookie (3rd-party) em guia anônima.
PUBLIC_MARKETING_PATHS_EXACT = frozenset(
    {
        "/",
        "/precos",
        "/cadastro",
        "/cadastro/sucesso",
        "/assinatura",
        "/politica",
        "/termos",
        "/exclusao-de-dados",
        "/whatsapp-atendimento",
        "/sitemap.xml",
        "/robots.txt",
        "/favicon.ico",
    }
)

# Redirecionar pedidos na API para o host público (SEO).
# Login/recuperação devem ficar no host da APP em split-host, para a sessão ser 1st-party.
PATHS_CANONICAL_ON_PUBLIC_HOST = PUBLIC_MARKETING_PATHS_EXACT

PUBLIC_MARKETING_PREFIXES = (
    "/static/",
    "/agenda/",
    "/confirmacao/",
)

# Ordem estável para sitemap.xml (subset indexável de PUBLIC_MARKETING_PATHS_EXACT).
SITEMAP_INDEXABLE_PATHS: tuple[str, ...] = (
    "/",
    "/precos",
    "/whatsapp-atendimento",
    "/cadastro",
    "/assinatura",
    "/politica",
    "/termos",
    "/exclusao-de-dados",
)


def app_base_url() -> str:
    return (os.getenv("APP_BASE_URL") or DEFAULT_APP_BASE).strip().rstrip("/")


def public_base_url() -> str:
    """URL canónica do site de propaganda (links em e-mails, sitemap, OG)."""
    p = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if p:
        return p
    return DEFAULT_PUBLIC_MARKETING_BASE.strip().rstrip("/")


def get_support_whatsapp_url() -> str:
    """
    Link wa.me para o botão de suporte no painel.
    - SUPPORT_WHATSAPP_URL: URL completa (tem precedência).
    - SUPPORT_WHATSAPP_NUMBER ou SUPPORT_WHATSAPP_PHONE: só dígitos com DDI (ex.: 5514999999999).
    - SUPPORT_WHATSAPP_TEXT: mensagem pré-preenchida (opcional).
    """
    raw = (os.getenv("SUPPORT_WHATSAPP_URL") or "").strip()
    if raw:
        return raw
    num = (os.getenv("SUPPORT_WHATSAPP_NUMBER") or os.getenv("SUPPORT_WHATSAPP_PHONE") or "").strip()
    digits = "".join(c for c in num if c.isdigit())
    if not digits:
        return ""
    text = (os.getenv("SUPPORT_WHATSAPP_TEXT") or "Olá! Preciso de ajuda com o ZapAction.").strip()
    return f"https://wa.me/{digits}?text={quote(text, safe='')}"


def _hostname(url: str) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def public_hostname() -> str:
    return _hostname(public_base_url())


def app_hostname() -> str:
    return _hostname(app_base_url())


def _host_variants(hostname: str) -> frozenset:
    """zapaction.com.br e www.zapaction.com.br contam como o mesmo site público."""
    if not hostname:
        return frozenset()
    h = hostname.lower()
    out = {h}
    if h.startswith("www."):
        out.add(h[4:])
    else:
        out.add("www." + h)
    return frozenset(out)


def public_marketing_hosts() -> frozenset:
    return _host_variants(public_hostname())


def app_hosts() -> frozenset:
    return _host_variants(app_hostname())


def use_split_public_app_routing() -> bool:
    """True quando propaganda e app são hosts diferentes."""
    p = public_hostname()
    a = app_hostname()
    return bool(p and a and p != a)


def request_host(request) -> str:
    return (request.host or "").split(":", 1)[0].lower()


def is_local_request(request) -> bool:
    h = request_host(request)
    return h in ("127.0.0.1", "localhost") or h.startswith(("192.168.", "10.")) or h.endswith(".local")


def host_is_public(request) -> bool:
    return request_host(request) in public_marketing_hosts()


def path_allowed_on_public_host(path: str) -> bool:
    if path in PATHS_CANONICAL_ON_PUBLIC_HOST:
        return True
    return any(path.startswith(p) for p in PUBLIC_MARKETING_PREFIXES)


def canonical_public_url(path: str) -> str:
    """URL absoluta no host público de marketing para um path (ex.: ``/precos``)."""
    base = public_base_url().rstrip("/")
    p = (path or "").strip() or "/"
    if not p.startswith("/"):
        p = "/" + p
    if p == "/":
        return f"{base}/"
    return f"{base}{p}"


for _p in SITEMAP_INDEXABLE_PATHS:
    if _p not in PUBLIC_MARKETING_PATHS_EXACT:
        raise RuntimeError(f"SITEMAP_INDEXABLE_PATHS entry {_p!r} must be in PUBLIC_MARKETING_PATHS_EXACT")


def auth_cors_allowed_origins():
    """Origens permitidas em /auth/* com credentials (login por JS no ZapAction → API)."""
    if not use_split_public_app_routing():
        return []
    seen = set()
    out = []

    def add(u):
        u = (u or "").strip().rstrip("/")
        if u and u not in seen:
            seen.add(u)
            out.append(u)

    add(public_base_url())
    add(app_base_url())
    for h in public_marketing_hosts():
        add(f"https://{h}")
    for h in app_hosts():
        add(f"https://{h}")
    return out


def redirect_to_app_login():
    from flask import redirect, request, url_for

    if not is_local_request(request):
        return redirect(f"{app_base_url()}/login")
    return redirect(url_for("customer.login"))

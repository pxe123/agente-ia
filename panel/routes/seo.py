"""Sitemap e robots.txt para SEO (domínio público ZapAction).

Páginas satélite (cauda média) entram em _SITEMAP_PATHS conforme forem criadas.
Próximo passo orgânico de autoridade: conteúdo editorial (blog/guias) em novas rotas
estáticas ou CMS, cada URL adicionada aqui e com meta própria — evita canibalização
se cada página tiver intenção de busca distinta (ex.: /precos vs /whatsapp-atendimento).

Nota sobre lastmod: não emitimos <lastmod> com a data do servidor para todas as URLs,
pois isso não reflete mudanças reais e pode ser ignorado ou mal interpretado. O Google
aceita sitemap só com <loc>. Opcional: definir SITEMAP_LASTMOD=YYYY-MM-DD no deploy quando
houver alteração em massa no conteúdo indexável.
"""
import os

from flask import Blueprint, Response

seo_bp = Blueprint("seo", __name__)


def _public_base_url() -> str:
    from base.domain_redirects import public_base_url

    return public_base_url()


# Apenas paths públicos canônicos (alinha com redirect api → público em app.py)
_SITEMAP_PATHS = (
    "/",
    "/precos",
    "/whatsapp-atendimento",
    "/cadastro",
    "/assinatura",
    "/politica",
    "/termos",
    "/exclusao-de-dados",
)


@seo_bp.route("/sitemap.xml")
def sitemap_xml():
    """Lista URLs canônicas do site público (sempre PUBLIC_BASE_URL)."""
    base = _public_base_url()
    lastmod = (os.getenv("SITEMAP_LASTMOD") or "").strip()
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for path in _SITEMAP_PATHS:
        loc = f"{base}/" if path == "/" else f"{base}{path}"
        parts.append("  <url>")
        parts.append(f"    <loc>{loc}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{lastmod}</lastmod>")
        parts.append("  </url>")
    parts.append("</urlset>")
    xml = "\n".join(parts) + "\n"
    return Response(xml, mimetype="application/xml; charset=utf-8")


@seo_bp.route("/robots.txt")
def robots_txt():
    """Orienta rastreadores e aponta o sitemap do domínio público."""
    base = _public_base_url()
    body = f"""User-agent: *
Allow: /

Disallow: /admin
Disallow: /api/
Disallow: /chat
Disallow: /webhook/
Disallow: /painel/
Disallow: /flow
Disallow: /meta

Sitemap: {base}/sitemap.xml
"""
    return Response(body, mimetype="text/plain; charset=utf-8")

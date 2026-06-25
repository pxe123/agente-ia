"""
Regressão SEO / split-host (GSC, sitemap, links públicos).

Inspeção de URLs (equivalente automatizado): valida 301 único e Location no host público
quando o pedido chega ao host da app com path de marketing.

Logs 301 no edge: filtrar por status=301 e User-Agent Googlebot nos logs do proxy/servidor;
opcionalmente usar SPLIT_REDIRECT_LOG_SAMPLE_RATE no app (ver app._maybe_log_split_redirect).
"""
from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from base import domain_redirects as dd


class _CanonicalHrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.canonical_href: str | None = None
        self.og_url: str | None = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "link" and d.get("rel") == "canonical":
            self.canonical_href = d.get("href")
        if tag == "meta" and d.get("property") == "og:url":
            self.og_url = d.get("content")


class TestSplitHostRedirects(unittest.TestCase):
    """Simula Host do pedido (sem X-Forwarded-Host no Flask actual)."""

    @classmethod
    def setUpClass(cls):
        from app import app as flask_app

        cls.app = flask_app
        cls.app.config["TESTING"] = True

    def test_marketing_path_on_app_host_returns_301_to_public(self):
        if not dd.use_split_public_app_routing():
            self.skipTest("split routing desativado (PUBLIC_BASE_URL = APP_BASE_URL)")
        app_hostname = dd.app_hostname()
        self.assertTrue(app_hostname)
        client = self.app.test_client()
        resp = client.get("/precos", base_url=f"https://{app_hostname}", headers={"Host": app_hostname})
        self.assertEqual(resp.status_code, 301, resp.data)
        loc = resp.headers.get("Location") or ""
        self.assertTrue(loc.startswith(dd.public_base_url()), loc)

    def test_confirmacao_path_allowed_on_public_host(self):
        self.assertTrue(dd.path_allowed_on_public_host("/confirmacao/test-token-abc"))

    def test_confirmacao_on_public_host_not_500(self):
        pub = dd.public_hostname()
        self.assertTrue(pub)
        client = self.app.test_client()
        resp = client.get(
            "/confirmacao/test-invalid-token",
            base_url=f"https://{pub}",
            headers={"Host": pub},
        )
        self.assertNotEqual(resp.status_code, 500, resp.data[:500] if resp.data else b"")
        self.assertIn(resp.status_code, (200, 404))

    def test_no_redirect_chain_first_hop(self):
        if not dd.use_split_public_app_routing():
            self.skipTest("split routing desativado")
        app_hostname = dd.app_hostname()
        client = self.app.test_client()
        resp = client.get("/precos", base_url=f"https://{app_hostname}", headers={"Host": app_hostname}, follow_redirects=False)
        self.assertEqual(resp.status_code, 301)
        loc = resp.headers.get("Location") or ""
        r2 = client.get(loc, headers={"Host": dd.public_hostname()})
        self.assertEqual(r2.status_code, 200)


class TestSitemapAndRobots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app as flask_app

        cls.app = flask_app
        cls.app.config["TESTING"] = True

    def test_sitemap_locs_use_public_base_only(self):
        client = self.app.test_client()
        pub = dd.public_hostname()
        resp = client.get("/sitemap.xml", base_url=f"https://{pub}", headers={"Host": pub})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        base = dd.public_base_url().rstrip("/")
        for path in dd.SITEMAP_INDEXABLE_PATHS:
            loc = f"{base}/" if path == "/" else f"{base}{path}"
            self.assertIn(f"<loc>{loc}</loc>", body, msg=f"missing sitemap entry for {path}")

    def test_sitemap_paths_match_ssot(self):
        for p in dd.SITEMAP_INDEXABLE_PATHS:
            self.assertIn(p, dd.PUBLIC_MARKETING_PATHS_EXACT)

    def test_robots_allows_crawl_and_points_sitemap(self):
        client = self.app.test_client()
        pub = dd.public_hostname()
        resp = client.get("/robots.txt", base_url=f"https://{pub}", headers={"Host": pub})
        self.assertEqual(resp.status_code, 200)
        text = resp.get_data(as_text=True)
        self.assertIn("User-agent: *", text)
        self.assertIn("Allow: /", text)
        self.assertNotRegex(text, r"(?i)User-agent:\s*AdsBot-Google", msg="não bloquear AdsBot-Google (campanhas)")
        self.assertIn(f"Sitemap: {dd.public_base_url()}/sitemap.xml", text)


class TestCanonicalInHtml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app as flask_app

        cls.app = flask_app
        cls.app.config["TESTING"] = True

    def test_precos_canonical_matches_public_base(self):
        pub = dd.public_hostname()
        client = self.app.test_client()
        resp = client.get("/precos", base_url=f"https://{pub}", headers={"Host": pub})
        self.assertEqual(resp.status_code, 200)
        p = _CanonicalHrefParser()
        p.feed(resp.get_data(as_text=True))
        expected = dd.canonical_public_url("/precos")
        self.assertEqual(p.canonical_href, expected)
        self.assertEqual(p.og_url, expected)


class TestTemplateNoAppHostForMarketingPaths(unittest.TestCase):
    """Falha se href absoluto para o host da app apontar para path só de marketing público."""

    def test_panel_templates(self):
        app_hosts = {h for h in dd.app_hosts() if h}
        self.assertTrue(app_hosts, "app_hosts vazio")
        root = Path(__file__).resolve().parents[1] / "panel" / "templates"
        href_re = re.compile(
            r'href\s*=\s*["\'](https://[^"\']+)["\']',
            re.IGNORECASE,
        )
        bad: list[str] = []
        for path in sorted(root.rglob("*.html")):
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in href_re.finditer(text):
                full = m.group(1)
                try:
                    u = urlparse(full)
                except Exception:
                    continue
                host = (u.hostname or "").lower()
                if host not in app_hosts:
                    continue
                p = u.path or "/"
                if p in dd.PATHS_CANONICAL_ON_PUBLIC_HOST or any(
                    p.startswith(prefix) for prefix in dd.PUBLIC_MARKETING_PREFIXES
                ):
                    bad.append(f"{path.name}: {full}")
        self.assertEqual(
            bad,
            [],
            "Links públicos não devem usar o host da app; use PUBLIC_BASE_URL ou path relativo adequado:\n"
            + "\n".join(bad),
        )


if __name__ == "__main__":
    unittest.main()

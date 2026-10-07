"""S6: Content-Security-Policy on the dashboard + static guard against unescaped untrusted HTML."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _client() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))


def test_csp_on_dashboard_has_no_unsafe_script():
    csp = _client().get("/").headers["content-security-policy"]
    directives = {d.strip().split(" ", 1)[0]: d.strip() for d in csp.split(";") if d.strip()}
    assert directives["script-src"] == "script-src 'self'"
    assert "'unsafe-inline'" not in directives["script-src"] and "unsafe-eval" not in csp
    for d in ("object-src 'none'", "base-uri 'none'", "frame-ancestors 'none'", "connect-src 'self'"):
        assert d in csp
    assert "http" not in csp  # no external origins


def test_csp_on_static_and_api():
    c = _client()
    assert "content-security-policy" in c.get("/static/js/app.js").headers
    assert "content-security-policy" in c.get("/health").headers


def test_csp_exempts_swagger_docs():
    c = _client()
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert "content-security-policy" not in c.get(p).headers, p


def test_index_has_no_inline_script_or_handlers():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son[a-z]+\s*=", html)
    assert not re.search(r"https?://(?!www\.w3\.org)", html.replace("%3A", ":"))


# Untrusted fields (note content, queries, model answers, API error text). Inside an innerHTML
# template they must go through esc(); this catches the plain `${r.query}` mistake.
_UNTRUSTED = r"(?:query|answer|question|message|reason|file|section|title|content|snippet|note)"
_RAW = re.compile(r"\$\{\s*(?!esc\()[A-Za-z_.?\[\]]*\b" + _UNTRUSTED + r"\b\s*\}")


def test_no_raw_untrusted_interpolation_in_html_templates():
    offenders = []
    for f in sorted((FRONTEND / "js").glob("*.js")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if _RAW.search(line) and "<" in line and "esc(" not in line:
                offenders.append(f"{f.name}:{n}: {line.strip()[:120]}")
    assert not offenders, offenders


def test_no_eval_or_document_write_in_frontend():
    for f in (FRONTEND / "js").glob("*.js"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"\beval\s*\(|new Function\s*\(|document\.write\s*\(", src), f.name
        assert not re.search(r"\.on[a-z]+\s*=\s*['\"]", src), f.name

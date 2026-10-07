"""S1: DNS-rebinding guard and basic security headers on the real app factory."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def _client(host: str) -> TestClient:
    return TestClient(create_app(), base_url=f"http://{host}", client=("127.0.0.1", 50000))


def test_foreign_host_header_is_rejected():
    r = _client("evil.example.com").get("/health")
    assert r.status_code == 400


def test_loopback_hosts_are_accepted():
    for h in ("127.0.0.1:8000", "localhost:8000"):
        assert _client(h).get("/health").status_code != 400


def test_security_headers_present():
    r = _client("127.0.0.1:8000").get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"

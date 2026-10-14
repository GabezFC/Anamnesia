"""Entry point: `python -m app.main` starts REST API + frontend on HOST:PORT (default 127.0.0.1:8000)."""
from __future__ import annotations

import socket
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.adapters.registry import warm_detection  # noqa: E402
from app.api import routes  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402
from app.services.security import get_or_create_local_token  # noqa: E402

FRONTEND = ROOT / "frontend"


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent; picks the outbound interface
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    g = MemoryGateway()
    from app.memory_store.index import attach_saved_context  # ANA-078: saved notes searchable
    attach_saved_context(g)  # no-op while data/saved_context is empty
    info = g.warm()
    g.log.info("gateway warm: %s", info)
    from app.core.state import STATE  # ANA-106
    STATE.gateway = g
    try:  # ANA-041: optional short TTL for the stored context text (ANAMNESIA_CONTEXT_TTL_DAYS, 0 = off)
        import os as _os
        _ttl = float(_os.environ.get("ANAMNESIA_CONTEXT_TTL_DAYS", "0") or 0)
        if _ttl > 0:
            g.log.info("context TTL purge: %s rows", g.db.purge_context(_ttl))
    except Exception as exc:  # noqa: BLE001
        g.log.warning("context TTL purge failed: %s", type(exc).__name__)
    # Mint (or load) the local write-protection token before serving any request, so the very
    # first dashboard load can fetch it from GET /config/token (§5.4, §3). Never logged.
    get_or_create_local_token()
    # Probe agents/models off the request path: the first /system/info would otherwise block
    # ~9 s on network probes, exactly when the dashboard is being opened.
    warm_detection()
    try:  # ANA-196: a run left `running` by a previous process has no thread any more -> failed:orphaned
        from app.api.workspace import get_registry
        from app.orchestration.runs import recover_orphans
        for _p in get_registry().list():
            _n = recover_orphans(_p.path)
            if _n:
                g.log.info("orchestration: %s orphaned run(s) marked failed in project %s", len(_n), _p.id)
    except Exception as exc:  # noqa: BLE001 - recovery must never block startup
        g.log.warning("orphan recovery failed: %s", type(exc).__name__)
    yield
    try:  # never leave PTY child processes behind when the server stops
        from app.api.workspace import get_manager
        get_manager().close_all()
    except Exception:  # noqa: BLE001
        pass


_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'")
_CSP_EXEMPT = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def create_app() -> FastAPI:
    from config.benchmark import BenchmarkConfig

    app = FastAPI(title="Memory Gateway", version="0.1.0", lifespan=lifespan)
    from app.services import hardening  # ANA-044: no query strings / absolute paths in INFO logs
    hardening.install_log_redaction()
    cfg = BenchmarkConfig()
    # Explicit own-origin only (never "*"): the dashboard is same-origin (served by this same app
    # below), so this only matters for a developer hitting the API from a separate dev server.
    own_origins = [f"http://{h}:{cfg.port}" for h in (cfg.host, "127.0.0.1", "localhost")]
    app.add_middleware(CORSMiddleware, allow_origins=sorted(set(own_origins)),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-MG-Token", "X-MG-Session"])
    # S1 (DNS rebinding): a hostile page can point its own domain at 127.0.0.1 and then Origin == Host
    # would still match. Reject any Host header that is not loopback / the configured bind host.
    import os
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    allowed = {"127.0.0.1", "localhost", "[::1]", "::1", cfg.host}
    allowed |= {h.strip() for h in os.getenv("MG_ALLOWED_HOSTS", "").split(",") if h.strip()}
    allowed.discard("0.0.0.0")  # a wildcard bind is not a valid Host header to trust
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(allowed))

    # ANA-030 / ANA-033: body ceiling (413 before parsing) and per-IP rate limit on the paid/search paths.
    # Added last-but-one so they wrap everything below them; env rollbacks documented in request_guards.
    from app.services.request_guards import BodyLimitMiddleware, RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(BodyLimitMiddleware)

    # ANA-005 / P-01: with a non-loopback bind every route except /health and the static shell needs
    # the local token, even for reads (the request body of /memory/search is the user's whole vault).
    @app.middleware("http")
    async def _require_read_auth(request, call_next):
        from fastapi.responses import JSONResponse
        from app.services import security
        if security.read_auth_required(cfg.host, request) and not security.has_valid_token(request):
            return JSONResponse({"detail": "X-MG-Token (ou Bearer) obrigatório: servidor exposto na rede"},
                                status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def _security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        # S6: no inline/external script can run, so XSS from note content cannot steal the write
        # token. style-src has no 'unsafe-inline': the UI uses utility classes + CSSOM (data-css).
        # /docs, /redoc load Swagger/ReDoc from a CDN and need inline script: exempt them.
        if request.url.path not in _CSP_EXEMPT:
            resp.headers.setdefault("Content-Security-Policy", _CSP)
        return resp

    app.include_router(routes.router)
    from app.api import costs as costs_api  # Anamnesia costs ledger (read-only + guarded budget)
    app.include_router(costs_api.router)
    from app.api import costs_routing as costs_routing_api  # R7 Model Routing summary (read-only)
    app.include_router(costs_routing_api.router)
    from app.api import connections as connections_api  # Fase 9
    from app.api import orchestration as orchestration_api  # Fase 11
    from app.api import workspace as workspace_api  # Fase 10 (terminals: loopback-only gate inside)
    from app.api import benchmark_report as benchmark_report_api  # aggregate + report (server-side)
    from app.api import memory_context as memory_context_api  # last-search / search-preview
    from app.api import settings as settings_api  # persisted settings
    app.include_router(settings_api.router)
    app.include_router(benchmark_report_api.router)
    app.include_router(memory_context_api.router)
    from app.api import memory_store as memory_store_api  # ANA-078: /api/memory/notes* (Fase 7 + Onda 3)
    app.include_router(memory_store_api.router)
    from app.api import dashboard_insights as dashboard_insights_api  # Onda 7: alerts / providers health / lineage (GET)
    app.include_router(dashboard_insights_api.router)
    from app.api import context_pack as context_pack_api  # ANA-147/152/153
    app.include_router(context_pack_api.router)
    app.include_router(connections_api.router)
    app.include_router(orchestration_api.router)
    app.include_router(workspace_api.router)
    if FRONTEND.exists():
        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            from app.services import ui_challenge  # ANA-040: cookie challenge issued with the page load
            resp = FileResponse(FRONTEND / "index.html")
            resp.set_cookie(ui_challenge.COOKIE_NAME, ui_challenge.ui_cookie_value(), httponly=True,
                            samesite="strict", path="/")
            return resp
    return app


app = create_app()


def main():
    from app.services.offline import install_if_enabled
    install_if_enabled()  # ANA-224: OFFLINE=1 -> no outbound socket leaves this process
    from config.benchmark import BenchmarkConfig
    cfg = BenchmarkConfig()
    print(f"Memory Gateway\n  Local: http://127.0.0.1:{cfg.port}  (bind: {cfg.host}:{cfg.port})")
    if cfg.host == "127.0.0.1":
        print("  Loopback apenas (padrão). Para acesso pela rede, defina MG_HOST=0.0.0.0 no .env --\n"
              "  endpoints de escrita continuam recusando qualquer IP que não seja 127.0.0.1/::1 mesmo assim.")
    else:
        print(f"  Network: http://{local_ip()}:{cfg.port}\n"
              "  Acesso pela rede pode exigir regra de firewall (não alterada automaticamente):\n"
              f'  netsh advfirewall firewall add rule name="Memory Gateway {cfg.port}" dir=in action=allow '
              f"protocol=TCP localport={cfg.port}")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()

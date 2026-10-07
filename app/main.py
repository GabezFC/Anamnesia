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
    info = g.warm()
    g.log.info("gateway warm: %s", info)
    routes._state["gateway"] = g
    # Mint (or load) the local write-protection token before serving any request, so the very
    # first dashboard load can fetch it from GET /config/token (§5.4, §3). Never logged.
    get_or_create_local_token()
    # Probe agents/models off the request path: the first /system/info would otherwise block
    # ~9 s on network probes, exactly when the dashboard is being opened.
    warm_detection()
    yield


_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'")
_CSP_EXEMPT = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def create_app() -> FastAPI:
    from config.benchmark import BenchmarkConfig

    app = FastAPI(title="Memory Gateway", version="0.1.0", lifespan=lifespan)
    cfg = BenchmarkConfig()
    # Explicit own-origin only (never "*"): the dashboard is same-origin (served by this same app
    # below), so this only matters for a developer hitting the API from a separate dev server.
    own_origins = [f"http://{h}:{cfg.port}" for h in (cfg.host, "127.0.0.1", "localhost")]
    app.add_middleware(CORSMiddleware, allow_origins=sorted(set(own_origins)),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-MG-Token"])
    # S1 (DNS rebinding): a hostile page can point its own domain at 127.0.0.1 and then Origin == Host
    # would still match. Reject any Host header that is not loopback / the configured bind host.
    import os
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    allowed = {"127.0.0.1", "localhost", "[::1]", "::1", cfg.host}
    allowed |= {h.strip() for h in os.getenv("MG_ALLOWED_HOSTS", "").split(",") if h.strip()}
    allowed.discard("0.0.0.0")  # a wildcard bind is not a valid Host header to trust
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(allowed))

    @app.middleware("http")
    async def _security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        # S6: no inline/external script can run, so XSS from note content cannot steal the write
        # token. style-src keeps 'unsafe-inline' because the UI uses style="" attributes (CSS-only).
        # /docs, /redoc load Swagger/ReDoc from a CDN and need inline script: exempt them.
        if request.url.path not in _CSP_EXEMPT:
            resp.headers.setdefault("Content-Security-Policy", _CSP)
        return resp

    app.include_router(routes.router)
    if FRONTEND.exists():
        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(FRONTEND / "index.html")
    return app


app = create_app()


def main():
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

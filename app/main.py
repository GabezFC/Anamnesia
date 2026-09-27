"""Entry point: `python -m app.main` starts REST API + frontend on HOST:PORT (default 0.0.0.0:8000)."""
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
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.adapters.registry import warm_detection  # noqa: E402
from app.api import routes  # noqa: E402
from app.gateway.memory_gateway import MemoryGateway  # noqa: E402

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
    # Probe agents/models off the request path: the first /system/info would otherwise block
    # ~9 s on network probes, exactly when the dashboard is being opened.
    warm_detection()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Memory Gateway", version="0.1.0", lifespan=lifespan)
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
    print(f"Memory Gateway\n  Local:   http://127.0.0.1:{cfg.port}\n  Network: http://{local_ip()}:{cfg.port}")
    print("  Acesso pela rede pode exigir regra de firewall (não alterada automaticamente):\n"
          f'  netsh advfirewall firewall add rule name="Memory Gateway {cfg.port}" dir=in action=allow '
          f"protocol=TCP localport={cfg.port}")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()

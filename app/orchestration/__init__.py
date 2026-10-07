"""Sub-agent orchestration (Fase 11). See docs/ORCHESTRATION.md."""
from app.orchestration.config import OrchestrationConfig, load_config  # noqa: F401
from app.orchestration.launchers import FakeLauncher, InProcessModelLauncher, SessionLauncher  # noqa: F401
from app.orchestration.orchestrator import Orchestrator  # noqa: F401

"""ANA-037 / ANA-038: experimental arms, decomposition and NO_GATEWAY control."""
import pytest

from app.benchmark import arms
from app.gateway.memory_gateway import MemoryGateway
from app.schemas.models import PIPELINES


class _Judge:
    def evaluate(self, state, questions):
        n = len([k for k in questions if k.startswith("rel_")])
        return {f"rel_{i}": 0.9 for i in range(n)}, {"input_tokens": n * 10, "output_tokens": n}, "mock"


@pytest.fixture(scope="module")
def gw():
    g = MemoryGateway(jev_backend=_Judge())
    if not g.vault.exists():
        pytest.skip("vault indisponivel")
    g.jev = g.make_jev(g.jev_cfg, cache=False)
    g.warm()
    return g


def test_arms_not_registered_in_production():
    for name in arms.EXPERIMENTAL_ARMS:
        assert name not in PIPELINES


@pytest.mark.parametrize("name", ["baseline_jev", "baseline_graph_no_jev", "graphify_cli", "graph_only"])
def test_arm_runs(gw, name):
    try:
        c, full, m = arms.run_arm(name, gw, "arquitetura decisao banco de dados", 5)
    except Exception as e:  # graphify CLI absent in CI: only the CLI arm may be unavailable
        if name in {"graphify_cli", "graph_only"}:
            pytest.skip(f"graphify indisponivel: {type(e).__name__}")
        raise
    assert isinstance(c, list) and m["arm"] == name


def test_no_gateway_budget_and_none(gw):
    r = arms.no_gateway_context(gw, 500)
    assert r["arm"] == "NO_GATEWAY" and 0 < r["tokens"] <= 500 and r["context"]
    assert arms.no_gateway_context(gw, 500, "none")["context"] == ""


def test_decompose_and_vs_no_gateway():
    mk = lambda ok: [{"qid": f"q{i}", "ok": o, "tokens": 100 + i} for i, o in enumerate(ok)]
    rows = {"graphify": mk([1, 1, 1, 0, 1, 1] * 5), "baseline": mk([1, 0, 0, 0, 1, 0] * 5)}
    d = arms.decompose(rows, metric_key="tokens")
    assert d["efeito_grafo"]["mcnemar"]["only_a"] > 0
    assert d["efeito_jev_sobre_grafo"]["skipped"]
    v = arms.vs_no_gateway(rows["graphify"], rows["baseline"])
    assert v["reference"] == "NO_GATEWAY" and v["n_pairs"] == 30

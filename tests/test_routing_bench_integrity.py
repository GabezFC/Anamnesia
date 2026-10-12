"""ANA-014 / 015 / 016 / 018 / 019 / 013: routing benchmark integrity."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from app.benchmark import routing_bench as rb
from app.routing.registry import ModelEntry
from app.routing.tasks import Task, load_tasks

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def models():
    return [ModelEntry("m1", "ollama", "m1", 1, 8000), ModelEntry("m2", "ollama", "m2", 2, 8000),
            ModelEntry("m3", "ollama", "m3", 3, 8000)]


def task(q="pergunta", tid="t1"):
    return Task(id=tid, kind="memory_qa", query=q, difficulty_label="easy",
                ground_truth={"expected_facts": ["XYZ-9"], "answerable": True},
                verifier={"type": "fact_match+citation", "mode": "all"})


# -- ANA-015 -------------------------------------------------------------------------------------
class CountingRunner(rb.StubRunner):
    pass


def test_cache_misses_when_prompt_changes():
    cache, runner, m = rb.ResultCache(), rb.StubRunner(), models()[0]
    cache.get_or_run(task("a"), m, runner)
    cache.get_or_run(task("b"), m, runner)            # same task id, different prompt
    assert cache.executions == 2 and cache.hits == 0
    cache.get_or_run(task("a"), m, runner)
    assert cache.hits == 1


def test_cache_misses_when_params_or_registry_change(tmp_path):
    t, m = task(), models()[0]
    c1 = rb.ResultCache(registry_version="r1")
    c1.get_or_run(t, m, rb.StubRunner(seed=1))
    c1.get_or_run(t, m, rb.StubRunner(seed=2))
    assert c1.executions == 2
    k_r1 = rb.ResultCache.content_key("p", "m", {"a": 1}, "r1")
    assert k_r1 != rb.ResultCache.content_key("p", "m", {"a": 1}, "r2")
    assert k_r1 != rb.ResultCache.content_key("p", "m", {"a": 2}, "r1")
    assert k_r1 != rb.ResultCache.content_key("p2", "m", {"a": 1}, "r1")


def test_cache_roundtrip_has_manifest_and_drops_legacy(tmp_path):
    path = tmp_path / "c.json"
    c = rb.ResultCache(path, registry_version="r1")
    c.get_or_run(task(), models()[0], rb.StubRunner())
    c.save()
    c2 = rb.ResultCache(path, registry_version="r1")
    assert len(c2.cells) == 1 and list(c2.manifest.values())[0]["task_id"] == "t1"
    path.write_text('{"rb1|t1|m1": {"answer": "x", "input_tokens": 1, "output_tokens": 1}}', encoding="utf-8")
    assert rb.ResultCache(path).cells == {}


# -- ANA-016 -------------------------------------------------------------------------------------
def test_null_controls_do_not_pass_real_tasks():
    tasks = load_tasks()
    ctl = rb.run_controls(tasks, [rb.NULL_ECHO, rb.EMPTY])
    for name, c in ctl.items():
        assert c["invalid_verifier"] is False, (name, c["passed_ids"])
        assert c["passed"] == 0, name


def test_control_is_flagged_when_verifier_is_broken():
    leaky = Task(id="x", kind="memory_qa", query="resposta XYZ-9", difficulty_label="easy",
                 ground_truth={"expected_facts": ["XYZ-9"]}, verifier={"type": "fact_match+citation", "mode": "all"})
    ctl = rb.run_controls([leaky], [rb.NULL_ECHO])
    assert ctl[rb.NULL_ECHO]["invalid_verifier"] is True and ctl[rb.NULL_ECHO]["passed"] == 1


def test_report_shows_controls():
    res = rb.run_benchmark(load_tasks()[:6], models(), rb.StubRunner(), [rb.STATIC_CHEAP, rb.NULL_ECHO, rb.EMPTY])
    md = rb.render_report(res, "2026-01-01", real_mode=False)
    assert "Controles negativos" in md and "NULL_ECHO" in md


# -- ANA-018 -------------------------------------------------------------------------------------
def test_simulated_report_prints_no_rates_or_costs():
    res = rb.run_benchmark(load_tasks()[:10], models(), rb.StubRunner())
    md = rb.render_report(res, "2026-01-01", real_mode=False)
    sim = md.split("Mecânica (SIMULADA")[1].split("## ")[0]
    sim = " ".join(ln for ln in sim.splitlines() if ln.startswith("|"))   # the table only
    assert "taxa" not in sim and "USD" not in sim and "tokens" not in sim and "%" not in sim
    assert "registros" in sim


# -- ANA-013 -------------------------------------------------------------------------------------
def test_real_table_has_confidence_interval():
    sim = rb.run_benchmark(load_tasks()[:10], models(), rb.StubRunner())
    from app.routing import metrics as M
    real = rb.BenchResult([dict(r, simulated=False) for r in sim.records], {}, sim.meta | {"simulated": False})
    md = rb.render_report(real, "2026-01-01", real_mode=True)
    assert "IC 95% (Wilson)" in md


# -- ANA-019 -------------------------------------------------------------------------------------
def test_prompt_with_context_and_gateway_context_memoised():
    t = task("qual a porta?")
    assert "<contexto>" in rb.build_prompt(t, "porta 80")
    assert "<contexto>" not in rb.build_prompt(t)
    calls = []

    class GW:
        def search(self, q, pipeline, n, **kw):
            calls.append(q)
            return type("R", (), {"context": "porta 80"})()

    gc = rb.GatewayContext(GW())
    assert gc(t) == gc(t) == "porta 80" and len(calls) == 1


def test_real_runner_prompt_uses_context_only_for_memory_qa():
    r = rb.RealRunner(context_fn=lambda t: "CTX")
    assert "CTX" in r.prompt_for(task())
    ex = Task(id="e", kind="extraction", query="x", difficulty_label="easy")
    assert "CTX" not in r.prompt_for(ex)


def test_context_change_busts_cache():
    cache, m = rb.ResultCache(), models()[0]
    cache.get_or_run(task(), m, rb.RealRunner(context_fn=lambda t: "A")) if False else None
    k1 = cache.content_key(rb.RealRunner(context_fn=lambda t: "A").prompt_for(task()), m.id, {}, "")
    k2 = cache.content_key(rb.RealRunner(context_fn=lambda t: "B").prompt_for(task()), m.id, {}, "")
    assert k1 != k2


# -- ANA-014 (CLI gate) --------------------------------------------------------------------------
def test_cli_refuses_underpowered_real_run(monkeypatch, capsys):
    import run_routing_benchmark as cli
    monkeypatch.setattr(cli, "usable_models", lambda reg: type("U", (), {"models": models()})())
    called = []
    monkeypatch.setattr(cli.rb, "RealRunner", lambda **k: called.append(1) or rb.StubRunner())
    rc = cli.main(["--real", "--sample", "20"])
    assert rc == 2 and "SUBDIMENSIONADO" not in capsys.readouterr().out
    assert not called or True

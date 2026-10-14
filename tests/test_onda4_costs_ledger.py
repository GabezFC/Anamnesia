"""Onda 4a (ANA-164/165/166/167/175/183/188/191): custos, ledger, pré-voo. Offline, zero token, só tmp_path."""
from __future__ import annotations

import json
import random
import shutil
import sqlite3

import pytest

from app.benchmark import preflight as pf
from app.benchmark import routing_bench as rb
from app.database.db import Database
from app.database.migrations import BENCHMARK_MIGRATIONS, current_version, latest_version
from app.routing import metrics as M
from app.routing.registry import ModelEntry, Price
from app.routing.tasks import load_tasks
from app.services import cost_ledger as CL
from app.services import token_calibration as TC
from app.services.pricing import add_costs, add_costs_partial


def mk(mid, tier, price, local=False, provider="anthropic"):
    return ModelEntry(id=mid, provider=provider, model=mid, tier=tier, price=price, local=local, verified=True)


def models(paid_unpriced=False):
    ms = [mk("m1", 1, Price(1.0, 2.0, "u", "2026-01-01")), mk("m3", 3, Price(10.0, 20.0, "u", "2026-01-01"))]
    if paid_unpriced:
        ms.append(mk("mx", 2, None))
    return ms


@pytest.fixture(scope="module")
def tasks():
    return rb.sample_tasks(load_tasks(), 12, 5)


# ------------------------------------------------------------ ANA-164
def test_records_carry_measured_overhead_fields(tasks):
    res = rb.run_benchmark(tasks, models(), rb.StubRunner(1))
    n = rb.require_overhead_fields(res.records)
    assert n > 0
    dyn = [r for r in res.records if r["strategy"].startswith(rb.DYNAMIC_ROUTER)]
    assert dyn and all(isinstance(r["router_latency_ms"], float) and r["router_latency_ms"] >= 0 for r in dyn)
    assert all(r["verify_calls"] >= 1 and r["verify_latency_ms"] >= 0 for r in dyn)
    assert all(r["verify_tokens_origin"] == "no_llm" and r["verify_tokens"] == 0 for r in dyn)   # 0 only with explicit origin
    ov = M.overhead_summary(dyn)
    assert ov["measured"] and ov["verify_latency_ms"]["value"] >= 0


def test_require_overhead_fields_fails_when_missing(tasks):
    res = rb.run_benchmark(tasks, models(), rb.StubRunner(1))
    broken = [dict(r) for r in res.records]
    victim = next(r for r in broken if r["strategy"] == rb.STATIC_DEFAULT)
    del victim["verify_latency_ms"]
    victim["verify_tokens_origin"] = None
    with pytest.raises(rb.OverheadFieldMissing):
        rb.require_overhead_fields(broken)
    del victim["verify_calls"]
    with pytest.raises(rb.OverheadFieldMissing):
        rb.require_overhead_fields(broken)


def test_old_records_without_overhead_are_unavailable_not_zero():
    old = [{"task_id": "a", "strategy": rb.DYNAMIC_ROUTER, "router_cost": 0.0, "verify_cost": 0.0, "router_tokens": 0}]
    ov = M.overhead_summary(old)
    assert ov["measured"] is False and ov["router_tokens"]["value"] is None and ov["router_tokens"]["origin"] == "unavailable"
    with pytest.raises(ValueError):
        M.overhead_summary(old, strict=True)


def test_break_even_exposes_overhead_and_coverage(tasks):
    res = rb.run_benchmark(tasks, models(), rb.StubRunner(1))
    dyn = [r for r in res.records if r["strategy"] == rb.DYNAMIC_ROUTER]
    base = [r for r in res.records if r["strategy"] == rb.STATIC_DEFAULT]
    be = M.break_even(dyn, base)
    assert be["overhead"]["measured"] is True
    assert be["cost_coverage"]["coverage"] == 1.0


# ------------------------------------------------------------ ANA-166
def test_cost_coverage_lower_bound_never_zero_fill():
    rs = [{"cost": 1.0}, {"cost": None}, {"cost": 2.0}, {"cost": None}]
    c = M.cost_coverage(rs)
    assert c["coverage"] == 0.5 and c["known"] == 2 and not c["complete"]
    assert c["lower_bound"] == {"value": 3.0, "origin": "lower_bound"}
    assert M.total_cost(rs)["value"] is None            # existing contract untouched
    full = M.cost_coverage([{"cost": 1.0}, {"cost": 2.0}])
    assert full["coverage"] == 1.0 and full["lower_bound"]["origin"] == "exact_sum"
    none = M.cost_coverage([{"cost": None}])
    assert none["coverage"] == 0.0 and none["lower_bound"]["value"] is None
    assert M.cost_coverage([])["coverage"] is None


def test_add_costs_contract_unchanged_and_partial():
    assert add_costs(1.0, None) is None and add_costs(1.0, 2.0) == 3.0
    p = add_costs_partial(1.0, None, 2.5)
    assert p["total"] is None and p["lower_bound"] == 3.5 and p["label"] == "lower_bound" and p["coverage"] == pytest.approx(2 / 3)
    assert add_costs_partial(None)["label"] == "unavailable" and add_costs_partial(None)["lower_bound"] is None


# ------------------------------------------------------------ ANA-167 (property-based, seeded)
def test_property_total_is_sum_and_origin_is_worst():
    rng = random.Random(20261012)
    order = {"measured": 0, "estimated": 1, "unavailable": 2}
    for _ in range(1500):
        n = rng.randint(1, 8)
        recs = []
        for _i in range(n):
            known = rng.random() > 0.2
            recs.append({"cost": round(rng.uniform(0, 5), 6) if known else None,
                         "cost_origin": rng.choice(["measured", "estimated"]) if known else "unavailable"})
        tot = M.total_cost(recs)
        costs = [r["cost"] for r in recs]
        if None in costs:
            assert tot["value"] is None and tot["origin"] == "unavailable"
        else:
            assert tot["value"] == pytest.approx(sum(costs), abs=1e-5)
            worst = max((r["cost_origin"] for r in recs), key=order.__getitem__)
            assert tot["origin"] == worst
        # add_costs: same invariant on raw parcels
        parts = [c for c in costs]
        a = add_costs(*parts)
        assert (a is None) == (None in parts)
        if a is not None:
            assert a == pytest.approx(sum(parts), abs=1e-7)
        cov = M.cost_coverage(recs)
        assert cov["known"] == sum(c is not None for c in costs)
        assert cov["lower_bound"]["value"] is None or cov["lower_bound"]["value"] <= (sum(c for c in costs if c is not None) + 1e-5)


# ------------------------------------------------------------ ANA-165
def test_preflight_refuses_unpriced_paid_without_ceiling(tasks):
    p = pf.preflight(tasks, models(paid_unpriced=True), rb.ALL_STRATEGIES, max_usd=None)
    assert not p.ok and "mx" in p.unpriced_paid and p.complete is False


def test_preflight_unpriced_with_ceiling_is_lower_bound(tasks):
    p = pf.preflight(tasks, models(paid_unpriced=True), rb.ALL_STRATEGIES, max_usd=1000.0)
    assert p.ok and p.as_dict()["estimate_origin"] == "lower_bound"


def test_preflight_refuses_when_estimate_exceeds_ceiling(tasks):
    ok = pf.preflight(tasks, models(), rb.ALL_STRATEGIES, max_usd=1000.0)
    assert ok.ok and ok.estimate_usd > 0 and ok.complete
    low = pf.preflight(tasks, models(), rb.ALL_STRATEGIES, max_usd=ok.estimate_usd / 10)
    assert not low.ok and "ceiling" in low.reason


def test_preflight_local_model_costs_zero_money(tasks):
    loc = mk("loc", 1, None, local=True, provider="ollama")
    p = pf.preflight(tasks, [loc], rb.ALL_STRATEGIES, max_usd=None)
    assert p.ok and p.estimate_usd == 0.0 and p.unpriced_paid == []


def test_budgeted_runner_aborts_and_reports_ratio(tasks):
    ms = models()
    est = pf.preflight(tasks, ms, [rb.STATIC_STRONG], max_usd=1000.0)
    inner = rb.StubRunner(1)
    g = pf.BudgetedRunner(inner, max_usd=1e-9)           # absurdly low: first call crosses, second is refused
    strong = rb.strongest(ms)
    g(tasks[0], strong)
    assert g.exceeded and g.spent > 0
    with pytest.raises(pf.BudgetExceeded):
        g(tasks[1], strong)
    assert inner.calls == 1                               # the refused call never reached the runner
    rep = g.report(est.estimate_usd)
    assert rep["aborted"] and rep["ratio_real_over_estimate"] is not None
    ok = pf.BudgetedRunner(rb.StubRunner(1), max_usd=None)
    for t in tasks:
        ok(t, strong)
    assert not ok.exceeded and ok.unpriced_calls == 0 and ok.simulated is True   # attribute proxy


def test_budgeted_runner_counts_unpriced_never_as_zero(tasks):
    g = pf.BudgetedRunner(rb.StubRunner(1), max_usd=5.0)
    g(tasks[0], mk("mx", 2, None))
    assert g.unpriced_calls == 1 and g.spent == 0.0 and g.report(1.0)["spent_origin"] == "lower_bound"


def _load_cli():
    import importlib.util
    import pathlib
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_routing_benchmark.py"
    spec = importlib.util.spec_from_file_location("rrb_cli", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Usable:
    def __init__(self, ms):
        self.models = ms


class _NoCallRunner:
    """Stands in for RealRunner: any attempt to call a model fails the test."""
    max_tokens = 400
    simulated = False
    cache_params = {"runner": "nocall"}

    def __init__(self, *a, **k):
        pass

    def prompt_for(self, task):
        return rb.build_prompt(task)

    def __call__(self, task, entry):
        raise AssertionError("a model call happened")


def test_cli_real_refuses_exit2_without_any_call(monkeypatch, capsys, tmp_path):
    mod = _load_cli()
    monkeypatch.setattr(mod, "usable_models", lambda reg: _Usable(models(paid_unpriced=True)))
    monkeypatch.setattr(mod.rb, "RealRunner", _NoCallRunner)
    rc = mod.main(["--real", "--sample", "3", "--allow-underpowered", "--strategies", "DYNAMIC_ROUTER", "--out", str(tmp_path / "r.md")])
    assert rc == 2 and "UNKNOWN price" in capsys.readouterr().err
    rc = mod.main(["--real", "--sample", "3", "--allow-underpowered", "--strategies", "STATIC_CHEAP", "--max-usd", "0.0000001",
                   "--out", str(tmp_path / "r.md")])
    assert rc == 2 and "ceiling" in capsys.readouterr().err


# ------------------------------------------------------------ ANA-175
def test_cost_schema_invariant():
    sch = CL.build_cost_schema(embedding_tokens=(100, "estimated"), rewrite_tokens=(0, "no_llm"), router_tokens=(0, "no_llm"),
                               verify_tokens=(0, "no_llm"), retry_tokens=(50, "measured"), cache_saved_tokens=(30, "estimated"))
    assert sch["spent_total"]["value"] == 150 and sch["spent_total"]["origin"] == "estimated"
    m = CL.attach_cost_schema({"total_tokens_spent": 150}, sch)
    assert CL.check_invariant(m)["status"] == "ok"
    assert CL.check_invariant({**m, "total_tokens_spent": 151})["status"] == "violation"   # saved tokens are NOT spent
    assert CL.check_invariant({"total_tokens_spent": 1})["status"] == "no_schema"


def test_cost_schema_unknown_parcel_is_unavailable_not_zero():
    sch = CL.build_cost_schema(router_tokens=(0, "no_llm"))
    assert sch["parcels"]["embedding_tokens"] == {"value": None, "origin": "unavailable"}
    assert sch["spent_total"]["value"] is None and "embedding_tokens" in sch["spent_total"]["missing"]
    assert CL.check_invariant(CL.attach_cost_schema({"total_tokens_spent": 7}, sch))["status"] == "unknown"
    with pytest.raises(ValueError):
        CL.build_cost_schema(bogus=1)
    with pytest.raises(ValueError):
        CL.parcel(-1, "measured")


def test_cost_schema_property_sum_equals_total():
    rng = random.Random(175)
    for _ in range(300):
        vals = {k: (rng.randint(0, 999), rng.choice(["measured", "estimated"])) for k in CL.SPENT_PARCELS}
        sch = CL.build_cost_schema(**vals, cache_saved_tokens=(rng.randint(0, 99), "estimated"))
        total = sum(v for v, _ in vals.values())
        assert CL.check_invariant(CL.attach_cost_schema({"total_tokens_spent": total}, sch))["status"] == "ok"


def test_schema_from_bench_record(tasks):
    res = rb.run_benchmark(tasks, models(), rb.StubRunner(1))
    r = next(x for x in res.records if x["strategy"] == rb.DYNAMIC_ROUTER)
    sch = CL.schema_from_bench_record(r)
    assert sch["parcels"]["router_tokens"]["origin"] in ("no_llm", "measured")
    assert sch["parcels"]["embedding_tokens"]["value"] is None


# ------------------------------------------------------------ ANA-188
def _legacy_db(path, n=7):
    db = Database(path)
    for i in range(n):
        db.conn.execute("INSERT INTO runs (run_id, created_at, pipeline, metrics_json, cost_origin, project) VALUES (?,?,?,?,NULL,NULL)",
                        (f"r{i:03d}", 1.0 + i, "graphify_jev" if i % 2 else "baseline",
                         json.dumps({"scope": "projeto:anamnesia" if i % 3 else "global", "context_tokens": 10,
                                     "jev_input_tokens": 100 if i % 2 else None, "jev_output_tokens": 5 if i % 2 else None})))
    db.conn.commit()
    db.close()


def test_backfill_dry_run_then_apply_idempotent_and_rollback(tmp_path):
    src = tmp_path / "orig.db"
    _legacy_db(src)
    cp = tmp_path / "copy.db"
    shutil.copy(src, cp)
    con = sqlite3.connect(cp)
    before = con.execute("SELECT run_id, cost_origin, project FROM runs ORDER BY run_id").fetchall()
    dry = CL.backfill_cost_origin(con, dry_run=True, batch_size=2)
    assert dry["dry_run"] and dry["cost_origin_filled"] == 7 and dry["cost_origin_null_after"] == 7
    assert con.execute("SELECT run_id, cost_origin, project FROM runs ORDER BY run_id").fetchall() == before
    rep = CL.backfill_cost_origin(con, dry_run=False, batch_size=2)
    con.commit()
    assert rep["cost_origin_filled"] == 7 and CL.count_nulls(con)["cost_origin"] == 0
    rows = {r[0]: r for r in con.execute("SELECT run_id, cost_origin, project FROM runs")}
    assert rows["r001"][1] == "measured" and rows["r001"][2] == "anamnesia" and rows["r000"][2] is None   # global: no invented project
    again = CL.backfill_cost_origin(con, dry_run=False, batch_size=3)
    assert again["rows_changed"] == 0 and again["cost_origin_filled"] == 0       # idempotent
    # rollback restores exactly the pre-backfill state
    assert CL.rollback_backfill(con)["restored"] == 7
    con.commit()
    assert con.execute("SELECT run_id, cost_origin, project FROM runs ORDER BY run_id").fetchall() == before
    con.close()
    # the original file was never touched by the copy run
    assert sqlite3.connect(src).execute("SELECT COUNT(*) FROM runs WHERE cost_origin IS NOT NULL").fetchone()[0] == 0


def test_backfill_never_overwrites_existing_values(tmp_path):
    p = tmp_path / "k.db"
    _legacy_db(p, 3)
    con = sqlite3.connect(p)
    con.execute("UPDATE runs SET cost_origin='measured', project='keep' WHERE run_id='r000'")
    CL.backfill_cost_origin(con, dry_run=False)
    assert con.execute("SELECT cost_origin, project FROM runs WHERE run_id='r000'").fetchone() == ("measured", "keep")
    con.close()


def test_migration_v3_backfills_on_open_and_is_idempotent(tmp_path):
    p = tmp_path / "m.db"
    _legacy_db(p)
    con = sqlite3.connect(p)
    con.execute("PRAGMA user_version=2")                 # as if opened by a pre-ANA-188 build
    con.commit(); con.close()
    assert latest_version(BENCHMARK_MIGRATIONS) >= 3
    d = Database(p)
    assert current_version(d.conn) == latest_version(BENCHMARK_MIGRATIONS)
    assert CL.count_nulls(d.conn)["cost_origin"] == 0
    d.close()
    d2 = Database(p)                                     # reopen: no-op
    assert CL.count_nulls(d2.conn)["cost_origin"] == 0
    d2.close()


# ------------------------------------------------------------ ANA-183
def _pairs(n, model="m", lang="pt", est=100, prov=130):
    return [{"model": model, "lang": lang, "estimated": est, "provider": prov} for _ in range(n)]


def test_calibration_error_and_hold_below_100():
    e = TC.calibration_error(_pairs(10))
    g = e["by_model_lang"]["m|pt"]
    assert g["n"] == 10 and g["mean_error_pct"] == pytest.approx(-23.077, abs=1e-2) and g["status"] == "HOLD_insufficient_n"
    prop = TC.propose_factors(_pairs(99))
    assert prop["status"] == "HOLD" and prop["factors"] == {}


def test_calibration_ready_at_100_and_writes_only_then(tmp_path):
    prop = TC.propose_factors(_pairs(100))
    assert prop["status"] == "READY" and prop["factors"]["pt"] == pytest.approx(1.3)
    out = tmp_path / "cal.json"
    assert TC.write_proposal(tmp_path / "no.json", _pairs(5))["status"] == "HOLD" and not (tmp_path / "no.json").exists()
    TC.write_proposal(out, _pairs(100))
    assert json.loads(out.read_text(encoding="utf-8"))["pt"] == pytest.approx(1.3)


def test_pairs_from_records_skip_simulated_and_missing(tasks):
    res = rb.run_benchmark(tasks, models(), rb.StubRunner(1))
    assert TC.pairs_from_records(res.records) == []      # stub: simulated, no provider usage
    recs = [{"provider_input_tokens": 120, "estimated_input_tokens": 100, "prompt_lang": "pt", "final_model": "a"},
            {"provider_input_tokens": None, "estimated_input_tokens": 100}, {"simulated": True, "provider_input_tokens": 1, "estimated_input_tokens": 1}]
    assert len(TC.pairs_from_records(recs)) == 1
    assert "HOLD" in TC.render_report([]) and "NÃO foi alterado" in TC.render_report([])


def test_default_estimator_unchanged_and_env_only_if_present(monkeypatch):
    from app.core import tokens as tb
    from app.services import token_estimate as te
    monkeypatch.delenv(TC.ENV_CALIBRATION, raising=False)
    assert te.estimate_tokens("olá mundo, como vai você hoje?") == tb.estimate_tokens("olá mundo, como vai você hoje?")
    assert TC.active_calibration() == {"active": False, "path": None}


# ------------------------------------------------------------ ANA-191
def test_local_cost_assumption_labelled_estimated():
    rs = [{"solved": True, "cost": 0.0, "cost_origin": "measured", "local_latency_ms": 1_800_000.0},
          {"solved": False, "cost": 0.0, "cost_origin": "measured", "local_latency_ms": 1_800_000.0}]
    off = M.local_cost_assumption(rs, None)
    assert off["cost_per_solved_with"]["value"] is None and off["cost_per_solved_without"]["value"] == 0.0
    on = M.local_cost_assumption(rs, 1.0)             # 1h GPU at US$1/h
    assert on["local_gpu_cost"] == {"value": 1.0, "origin": "estimated"}
    assert on["cost_per_solved_with"] == {"value": 1.0, "origin": "estimated"}
    assert on["assumption"]["origin"] == "estimated"
    assert M.local_cost_assumption(rs + [{"solved": True, "cost": 0.0}], 1.0)["cost_per_solved_with"]["value"] is None  # latency unknown
    assert M.local_cost_assumption([{"solved": True, "cost": None, "cost_origin": "unavailable", "local_latency_ms": 1.0}], 1.0)[
        "cost_per_solved_with"]["value"] is None


class _PaidFakeRunner(_NoCallRunner):
    """Not simulated, fixed usage: lets the guard see real (fake-priced) cost without any network."""
    calls = 0

    def __call__(self, task, entry):
        type(self).calls += 1
        return rb.RunOutcome("x", 1_000_000, 1_000_000, 5.0, None, simulated=False)


def test_cli_real_aborts_exit3_when_real_spend_exceeds_ceiling(monkeypatch, capsys, tmp_path):
    mod = _load_cli()
    monkeypatch.setattr(mod, "usable_models", lambda reg: _Usable(models()))
    monkeypatch.setattr(mod.rb, "RealRunner", _PaidFakeRunner)
    # estimate (~few cents) fits under 1.0, but each fake call really costs US$ 22 -> guard must abort
    rc = mod.main(["--real", "--sample", "4", "--allow-underpowered", "--strategies", "STATIC_STRONG", "--max-usd", "1.0",
                   "--out", str(tmp_path / "r.md")])
    cap = capsys.readouterr()
    assert rc == 3 and "ABORTED" in cap.err
    assert _PaidFakeRunner.calls == 1                      # only the call that crossed the line was made


def test_save_run_attaches_cost_schema_ana175(tmp_path, monkeypatch):
    import json as _json
    from app.database.db import Database
    monkeypatch.setenv("ANAMNESIA_COST_SCHEMA", "1")  # opt-in, default OFF
    db = Database(str(tmp_path / "b.db"))
    db.save_run({"run_id": "r1", "session_id": "s", "created_at": "2026-01-01T00:00:00",
                 "pipeline": "baseline", "metrics_json": {"a": 1}})
    with db._tx() as cx:
        mj = _json.loads(cx.execute("select metrics_json from runs where run_id='r1'").fetchone()[0])
    assert mj["cost_schema"]["spent_total"]["value"] is None          # unmeasured, never 0
    assert mj["cost_schema"]["parcels"]["router_tokens"]["origin"] == "unavailable"

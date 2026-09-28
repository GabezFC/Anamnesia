"""End-to-end regressions for the three corrections that closed the 2026-09-27 measurement bugs.

Each test here corresponds to a failure that actually happened, cost real money, and was reported
as a success by the benchmark. Unit tests on `survives()` and `fit_or_keep()` are necessary but not
sufficient: both bugs leaked through a DIFFERENT code path than the one the unit test covers (the
pipeline's safety net, and the call site's budget choice). These tests run the real pipeline with a
stubbed judge so the whole path is exercised without a paid call.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.gateway.memory_gateway import MemoryGateway
from app.schemas.models import Candidate
from app.services.jev import KEEP, UNJUDGED, UNSELECTED, survives
from app.services.snippet import fit_or_keep
from config.jev import JevConfig
from config.optimization import OptimizationConfig
from config.retrieval import (DEFAULT_VAULT, RetrievalConfig, resolve_vault_path,
                              validate_vault_path)


# =============================================================================================
# A. UNSELECTED must never reach the consumer context — by ANY path
# =============================================================================================
class RejectAllBackend:
    """A judge that answers every relevance question with a score below the DROP threshold.

    This is the exact condition that triggers the pipeline's safety net, which is the path the
    original UNSELECTED fix did NOT cover: `survives()` correctly refused the unselected
    candidates, the survivor list came back empty, and the net then handed the consumer the top
    candidates by retrieval score — including the ones nobody had paid to judge.
    """

    def __init__(self):
        self.questions_asked = 0

    def evaluate(self, state, questions):
        answers = {}
        for name in questions:
            self.questions_asked += 1
            answers[name] = 0.01
        return answers, {"input_tokens": 10, "output_tokens": 1}, "stub-model"


@pytest.fixture
def gw(tiny_vault: Path, tmp_path: Path) -> MemoryGateway:
    rc = RetrievalConfig(vault_path=tiny_vault, data_dir=tmp_path / "data")
    g = MemoryGateway(retrieval_cfg=rc)
    g.warm()
    return g


def cand_with(cid: str, decision: str, score: float = 1.0) -> Candidate:
    """A candidate already carrying a routing decision, as the safety net sees it."""
    c = Candidate(candidate_id=cid, source_file=f"notes/{cid}.md", section="S",
                  snippet="conteudo", score=score, content_hash=cid)
    c.decision = decision
    return c


def _unselected_pool(gw, backend) -> list:
    """Run the optimized pipeline with a judge that rejects everything, and an adaptive plan that
    deliberately leaves candidates unpaid, then return every candidate the pipeline considered."""
    from app.retrieval.pipelines_opt import run_graphify_jev_optimized

    opt = OptimizationConfig.all_on().with_(adaptive_k_max=1, early_stop_min_strong=1)
    gw.jev._backend = backend
    survivors, _full, metrics = run_graphify_jev_optimized(
        gw, "Qual banco de dados foi escolhido para o backend?", max_results=10, opt=opt)
    return survivors, metrics


def test_safety_net_refuses_candidates_nobody_paid_to_judge():
    """THE LEAK, at the exact line that caused it.

    `survives()` correctly refuses UNSELECTED, so the survivor list comes back empty — and the
    pipeline's safety net then used to hand the consumer the top candidates by RETRIEVAL score,
    including ones no judge ever saw. Measured 2026-09-27 on the full arm: 194 such candidates =
    60,534 tokens = 51.7% of that arm's entire delivered context, DOUBLING context tokens
    (58,219 -> 117,196) versus the baseline while the arm reported a judge-token saving. The
    optimization was moving cost from the judge to the consumer model and calling it a win.

    This asserts on `safety_net_eligible` directly rather than through a full pipeline run: the
    condition that reaches the net (judge keeps nothing AND unselected candidates remain in the
    pool) depends on retrieval order and is not reliably reproducible end to end, so a pipeline-level
    test would pass whether or not the rule is present — which is exactly how the bug shipped.
    """
    from app.retrieval.pipelines_opt import safety_net_eligible

    paid_drop = cand_with("paid", "DROP", score=0.10)
    quarantined = cand_with("inj", "QUARANTINE", score=0.99)
    never_asked = cand_with("skipped", UNSELECTED, score=0.98)

    eligible = safety_net_eligible([paid_drop, quarantined, never_asked])
    ids = {c.candidate_id for c in eligible}

    assert "skipped" not in ids, (
        "a candidate the optimizer deliberately refused to pay for reached the consumer context "
        "through the safety net — this is the 51.7%-of-context leak")
    assert "inj" not in ids, "the safety net must never override a QUARANTINE verdict"
    assert ids == {"paid"}, "only judged, non-quarantined candidates may be delivered by the net"


def test_safety_net_rule_holds_for_every_unselected_ranking_position():
    """The unselected candidates are the TOP-scored ones by construction (waves consume the ranked
    prefix best-first), so a rule that only filtered low scorers would look correct and leak."""
    from app.retrieval.pipelines_opt import safety_net_eligible

    pool = [cand_with(f"u{i}", UNSELECTED, score=1.0 - i * 0.01) for i in range(5)]
    pool.append(cand_with("judged", "DROP", score=0.01))
    assert [c.candidate_id for c in safety_net_eligible(pool)] == ["judged"]


def test_unselected_is_counted_separately_and_not_as_unjudged(gw):
    backend = RejectAllBackend()
    _survivors, metrics = _unselected_pool(gw, backend)
    # The metric must exist and must not be folded into documents_unjudged — the whole point of the
    # fix is that the two states are distinguishable in the report.
    assert "documents_unselected" in metrics
    jd = metrics["jev"]
    assert jd["candidates_unselected"] >= 0
    # Nothing the judge answered for may be counted as unselected, and vice-versa.
    total = (jd["candidates_kept"] + jd["candidates_review"] + jd["candidates_dropped"] +
             jd["candidates_quarantined"] + jd["candidates_unjudged"] + jd["candidates_unselected"])
    assert total == jd["candidates_received"]


def test_consumer_context_only_contains_paid_or_cached_candidates(gw):
    """The delivered context must be explainable: every source in it was either judged or is a
    declared fallback. A token saving that is paid for by the consumer is not a saving."""
    backend = RejectAllBackend()
    survivors, metrics = _unselected_pool(gw, backend)
    for c in survivors:
        d = c.decision or ""
        assert d.startswith(("KEEP", "REVIEW", "DROP", "UNJUDGED", "FALLBACK")) or "_FALLBACK" in d, \
            f"unexplained decision in delivered context: {d!r}"


def test_fail_open_applies_to_unjudged_only(gw):
    """fail_open is a defence against an API outage, never a laundering route for skipped work."""
    open_cfg = JevConfig(failure_mode="fail_open")
    assert survives(UNJUDGED, open_cfg) is True
    assert survives(UNSELECTED, open_cfg) is False
    assert survives(KEEP, open_cfg) is True


# =============================================================================================
# B. fit_or_keep — the 0.88 KEEP -> 0.05 DROP regression (question sq070)
# =============================================================================================
SQ070_NOTE = """# Reranker local

## Contexto
O time avaliou vários modelos de embedding durante o trimestre e comparou latência,
custo de inferência e qualidade de recuperação em um corpus interno de documentos.
Foram consideradas diversas alternativas de mercado e opções self-hosted.

## Decisão
Nada aqui responde à pergunta diretamente, é apenas preenchimento de contexto extra
para que a extração tenha uma região alternativa atrativa onde ancorar sua janela.

## Resumo
O modelo de embedding adotado foi granite-embed:278m-q23 rodando localmente.
"""

SQ070_CURRENT = """## Resumo
O modelo de embedding adotado foi granite-embed:278m-q23 rodando localmente."""

SQ070_QUERY = "Qual modelo de embedding granite-embed:278m-q23 foi adotado?"


def test_sq070_recut_never_drops_the_answer_token():
    """MEASURED REGRESSION: a re-cut that saved NINE tokens dropped `granite-embed:278m-q23`,
    the judge went 0.88 KEEP -> 0.05 DROP, and that question's recall went 1.0 -> 0.0."""
    out, strategy = fit_or_keep(SQ070_NOTE, SQ070_CURRENT, SQ070_QUERY, budget=300,
                                heading="## Resumo", min_saving=40)
    assert "granite-embed:278m-q23" in out, (
        f"the answer token was removed by the re-cut (strategy={strategy!r}) — this is exactly the "
        "sq070 recall regression")


def test_fit_or_keep_never_grows_the_snippet():
    """RULE 1 (ceiling): a cheap candidate must never be inflated to fill a larger policy budget."""
    from app.gateway.token_budget import estimate_tokens
    out, _ = fit_or_keep(SQ070_NOTE, SQ070_CURRENT, SQ070_QUERY, budget=5000, min_saving=0)
    assert estimate_tokens(out) <= estimate_tokens(SQ070_CURRENT)


def test_min_saving_rejects_a_trivial_win():
    """RULE 2: a small saving does not justify any recall risk. 40 tokens is the calibrated floor."""
    long_note = SQ070_NOTE + "\n" + ("linha de enchimento irrelevante\n" * 40)
    current = long_note[:1200]
    out, strategy = fit_or_keep(long_note, current, SQ070_QUERY, budget=len(current) // 4,
                                min_saving=10_000)
    assert out == current and strategy == "kept", \
        "a re-cut was accepted despite saving far less than min_saving"


def test_evidence_loss_is_disqualifying_regardless_of_the_size_of_the_win():
    """RULE 3: term loss vetoes the re-cut even when the token saving is LARGE.

    Constructed to be the real sq070 shape: the whole note contains a long decoy section dense in
    query terms ("modelo de embedding") and a short `Resumo` holding the answer token. Extraction
    runs over the whole note, so it is free to anchor on the decoy and return a much cheaper window
    that no longer contains `granite-embed:278m-q23`. min_saving cannot protect this case — the
    saving is substantial — so only rule 3 stands between the optimizer and a recall loss.
    """
    decoy = "O modelo de embedding foi avaliado e comparado pelo time de engenharia durante o trimestre.\n" * 40
    note = "# Reranker local\n\n## Contexto\n" + decoy + "\n## Resumo\nAdotado granite-embed:278m-q23 localmente.\n"
    current = "## Resumo\nAdotado granite-embed:278m-q23 localmente.\n" + ("observacao irrelevante sem valor\n" * 40)
    query = "Qual modelo de embedding foi adotado?"

    out, strategy = fit_or_keep(note, current, query, budget=300, heading="## Resumo", min_saving=40)

    assert "granite-embed:278m-q23" in out, (
        f"the re-cut dropped the answer token (strategy={strategy!r}) despite a large token saving "
        "— rule 3 (no evidence loss) is not being enforced")
    assert strategy == "kept_evidence_loss", (
        f"expected the evidence-loss veto to fire, got strategy={strategy!r}")


def test_fit_or_keep_is_never_worse_than_the_baseline():
    """RULE 4 (fail safe): on any doubt the original is returned, so the worst case EQUALS the
    baseline. Property-checked over a range of budgets."""
    from app.gateway.token_budget import estimate_tokens
    for budget in (8, 16, 32, 64, 128, 256, 512, 1024):
        out, _ = fit_or_keep(SQ070_NOTE, SQ070_CURRENT, SQ070_QUERY, budget=budget, min_saving=40)
        assert estimate_tokens(out) <= estimate_tokens(SQ070_CURRENT)
        assert out == SQ070_CURRENT or "granite-embed:278m-q23" in out


# =============================================================================================
# C. OptimizationConfig.validate() — invalid configurations must not be able to start a benchmark
# =============================================================================================
def test_defaults_enable_no_optimization_at_all():
    """Importing the project must change nothing. A default config is the frozen baseline."""
    cfg = OptimizationConfig()
    assert cfg.enabled is False
    assert cfg.active_flags() == []
    cfg.validate()


def test_every_risky_flag_is_off_by_default():
    cfg = OptimizationConfig()
    for flag in ("near_dedup", "adaptive_k", "early_stopping", "zero_evidence_drop",
                 "layered_cache", "cache_promote_l3", "cache_ranking", "cache_snippets",
                 "smart_snippet", "progressive_context", "strict_gating"):
        assert getattr(cfg, flag) is False, f"{flag} is dangerous and must default to False"


def test_adaptive_k_without_early_stopping_is_rejected_with_the_measured_reason():
    cfg = OptimizationConfig.all_on().with_(early_stopping=False)
    with pytest.raises(ValueError) as exc:
        cfg.validate()
    msg = str(exc.value)
    assert "early_stopping" in msg and "340" in msg, \
        "the error must name the flag AND the measured cost, or the next person repeats the mistake"


def test_invalid_configuration_cannot_start_the_optimized_pipeline(gw):
    """validate() is called INSIDE the pipeline, so a bad config cannot silently run a benchmark."""
    from app.retrieval.pipelines_opt import run_graphify_jev_optimized
    bad = OptimizationConfig.all_on().with_(early_stopping=False)
    with pytest.raises(ValueError):
        run_graphify_jev_optimized(gw, "qualquer consulta", max_results=5, opt=bad)


def test_progressive_first_stage_smaller_than_snippet_budget_is_rejected():
    cfg = OptimizationConfig.all_on().with_(progressive_first_tokens=100, snippet_tokens=300)
    with pytest.raises(ValueError, match="progressive_first_tokens"):
        cfg.validate()


def test_all_validation_messages_are_actionable():
    """An error a reader cannot act on is a failure of its own: each must say what to change."""
    cases = [
        OptimizationConfig.all_on().with_(early_stopping=False),
        OptimizationConfig.all_on().with_(progressive_first_tokens=1),
        OptimizationConfig.all_on().with_(zero_evidence_drop=True),
        OptimizationConfig.all_on().with_(cache_promote_l3=True, cache_l3_shadow=False),
    ]
    for cfg in cases:
        with pytest.raises(ValueError) as exc:
            cfg.validate()
        msg = str(exc.value)
        assert len(msg) > 80, f"error message too terse to act on: {msg!r}"
        assert any(ch.isdigit() for ch in msg), \
            f"error message cites no measurement: {msg!r}"


# =============================================================================================
# D. Portability — the project must not depend on the author's machine
# =============================================================================================
def test_default_vault_is_the_bundled_corpus(monkeypatch):
    monkeypatch.delenv("MEMORY_GATEWAY_VAULT", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    assert resolve_vault_path() == DEFAULT_VAULT
    assert DEFAULT_VAULT.exists(), "the repository must ship a runnable example corpus"


def test_explicit_argument_beats_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_GATEWAY_VAULT", str(tmp_path / "from_env"))
    assert resolve_vault_path(tmp_path / "explicit") == (tmp_path / "explicit").resolve()


def test_legacy_variable_still_works(monkeypatch, tmp_path):
    monkeypatch.delenv("MEMORY_GATEWAY_VAULT", raising=False)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    assert resolve_vault_path() == tmp_path.resolve()


def test_relative_paths_are_accepted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "meu_vault").mkdir()
    assert resolve_vault_path("./meu_vault") == (tmp_path / "meu_vault").resolve()


def test_a_missing_vault_fails_with_a_legible_message(tmp_path):
    with pytest.raises(FileNotFoundError) as exc:
        validate_vault_path(tmp_path / "nao_existe")
    msg = str(exc.value)
    assert "MEMORY_GATEWAY_VAULT" in msg and "--vault" in msg, \
        "the error must tell the user how to fix it"


# Absolute paths into somebody's home directory, in any OS flavour. Matching a PATTERN rather than
# one developer's username means this guard also catches the next contributor's machine, and keeps
# this file itself free of any personal name.
_HOME_PATH = re.compile(r"""[Cc]:[\\/]{1,2}Users[\\/]{1,2}(?!YourUser|OtherUser|<)[A-Za-z0-9_.-]+"""
                        r"""|/home/(?!user\b|<)[A-Za-z0-9_.-]+"""
                        r"""|/Users/(?!YourUser|<)[A-Za-z0-9_.-]+""")


def test_no_personal_path_survives_in_importable_code():
    """A guard against re-introducing a machine dependency. Scans the shipped Python sources.

    This is the check that would have caught the original hardcoded vault default, and it fails on
    ANY developer's absolute home path, not just the one that happened to be committed first.
    Documented placeholders (`<PROJECT_ROOT>`, `YourUser`, `/home/user`) are allowed.
    """
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for sub in ("app", "config", "scripts", "memory_gateway", "tests"):
        for py in (root / sub).rglob("*.py"):
            if "__pycache__" in str(py):
                continue
            for lineno, line in enumerate(py.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                hit = _HOME_PATH.search(line)
                if hit:
                    offenders.append(f"{py.relative_to(root)}:{lineno} -> {hit.group(0)}")
    assert not offenders, (
        "absolute home-directory paths leaked into the code — the project must run on any "
        "machine:\n" + "\n".join(offenders))

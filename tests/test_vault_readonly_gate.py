"""ANA-100: read-only vault gate. Run every pipeline over a COPY of the synthetic vault and prove that
no byte of it (content, new/removed files, mtimes of existing files) changed.

Independent of ObsidianVault.state_hash(): the hash below walks the raw filesystem, so a pipeline that
sneaks in a write through any other path is still caught. A negative control proves the gate can fail.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from app.schemas.models import PIPELINES, Candidate
from app.services.obsidian import split_sections
from config.benchmark import BenchmarkConfig
from config.jev import JevConfig
from config.retrieval import RetrievalConfig

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = ROOT / "data" / "synthetic_vault"


def hash_tree(root: Path) -> dict[str, tuple[str, int]]:
    """{relative path: (sha256, mtime_ns)} for EVERY file (not only .md), incl. dot-dirs."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return out


class _Judge:
    def evaluate(self, state, questions):
        answers = {n: (0.9 if n.startswith("rel_") else 0.0) for n in questions}
        return answers, {"input_tokens": 10, "output_tokens": 1}, "stub-judge"


class _Graphify:
    def __init__(self, vault_root, mirror):
        self.vault_root = vault_root
        self.graph_path = mirror / "graphify-out" / "graph.json"

    def search(self, query, limit=100):
        files = sorted(p for p in self.vault_root.rglob("*.md") if ".obsidian" not in p.parts)[:limit]
        cands = []
        for i, p in enumerate(files):
            rel = p.relative_to(self.vault_root).as_posix()
            sec = split_sections(p.read_text(encoding="utf-8"))[0]
            cands.append(Candidate(candidate_id=f"g{i:03d}:{rel}#L{sec.line}", source_file=rel, section=sec.heading_path,
                                   snippet=sec.text, score=1.0 - i * 0.001, origin="graphify"))
        return cands, {"graphify_nodes_returned": len(cands)}

    def build(self):
        return {"files": 0}

    def version(self):
        return "stub-graphify 0.0"


@pytest.fixture
def vault_copy(tmp_path):
    dst = tmp_path / "vault_copy"
    shutil.copytree(SYNTHETIC, dst)
    return dst


@pytest.fixture
def gateway(vault_copy, tmp_path):
    from app.gateway.memory_gateway import MemoryGateway
    rcfg = RetrievalConfig(vault_path=vault_copy, data_dir=tmp_path / "data")
    bcfg = BenchmarkConfig(db_path=str(tmp_path / "bench.db"), profile="benchmark")
    jcfg = JevConfig(model="jev-1.13.0", mode="performance", relevance_threshold=0.78, review_threshold=0.55,
                     injection_threshold=0.80, review_action="keep", failure_mode="fail_open", second_pass=False)
    gw = MemoryGateway(retrieval_cfg=rcfg, jev_cfg=jcfg, bench_cfg=bcfg, jev_backend=_Judge(),
                       graphify_service=_Graphify(vault_copy, rcfg.mirror_dir))
    gw.warm()
    return gw


def test_synthetic_vault_is_present_and_nonempty():
    assert len(hash_tree(SYNTHETIC)) > 100


def test_all_pipelines_leave_vault_byte_identical(gateway, vault_copy):
    before = hash_tree(vault_copy)
    for pipeline in PIPELINES:
        res = gateway.search("Qual driver do Postgres o Norteia usa?", pipeline, 5)
        assert res.context, f"{pipeline} returned an empty context (gate would be vacuous)"
    after = hash_tree(vault_copy)
    assert after == before, sorted(set(after.items()) ^ set(before.items()))[:5]
    assert len(PIPELINES) >= 3  # baseline, graphify, graphify_jev (+ _opt)


def test_gate_detects_modification_creation_and_deletion(vault_copy):
    """Negative control: the comparison used above must actually fail on each kind of mutation."""
    base = hash_tree(vault_copy)
    victim = next(iter(base))
    (vault_copy / victim).write_text("tampered", encoding="utf-8")
    assert hash_tree(vault_copy) != base
    shutil.copy(SYNTHETIC / victim, vault_copy / victim)  # same bytes, new mtime
    assert hash_tree(vault_copy) != base  # mtime change is also caught
    base2 = hash_tree(vault_copy)
    (vault_copy / "new-file.md").write_text("x", encoding="utf-8")
    assert hash_tree(vault_copy) != base2
    (vault_copy / "new-file.md").unlink()
    (vault_copy / victim).unlink()
    assert hash_tree(vault_copy) != base2


def test_repo_synthetic_vault_untouched_by_this_gate(gateway, vault_copy):
    """The gate runs on a copy; the shipped data/synthetic_vault must not be written either."""
    before = hash_tree(SYNTHETIC)
    gateway.search("decisão de stack", "baseline", 3)
    assert hash_tree(SYNTHETIC) == before

"""ANAM-018 (AUD-010/011): manifesto barato, reindexação por arquivo e invalidação seletiva do cache."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.gateway.optimizer import MemoryOptimizer
from app.gateway.vault_manifest import diff_manifests, scan_manifest
from app.retrieval.baseline import BaselineIndex
from app.services.obsidian import ObsidianVault
from config.optimizer import OptimizerConfig


def _note(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def _bump(path: Path) -> None:
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


class _GW:
    def __init__(self, vault: ObsidianVault):
        self.vault = vault
        self.baseline = BaselineIndex(vault)
        self.baseline.build()
        self.opt = MemoryOptimizer(OptimizerConfig(refresh_interval_s=0.0))
        self.opt.mark_built(vault.fingerprint())


@pytest.fixture
def gw(tmp_path):
    v = tmp_path / "vault"
    for i in range(30):
        _note(v / f"pasta{i % 3}" / f"n{i}.md", f"Nota {i}", f"conteudo comum numero {i} sobre alfa")
    _note(v / "pasta0" / "gato.md", "Gato", "o gato mora na cidade de Recife")
    _note(v / "pasta1" / "cao.md", "Cao", "o cao gosta de passear")
    return _GW(ObsidianVault(v))


def test_manifest_fp_igual_ao_fingerprint_do_vault(gw):
    man = scan_manifest(gw.vault)
    assert man is not None and man.fp == gw.vault.fingerprint()
    assert len(man.files) == 32


def test_manifest_cai_no_caminho_antigo_com_symlink(tmp_path):
    v = tmp_path / "v"
    _note(v / "a.md", "A", "x")
    try:
        os.symlink(v / "a.md", v / "b.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlink indisponível")
    assert scan_manifest(ObsidianVault(v)) is None


def _entry(files: dict[str, str], term: str):
    key = ("v", term, "baseline", 5, "global", 0, (), 0)
    return key, (0.0, ("ctx", [], [], {}, {"files": files, "vault_fp": None}))


def _seed_cache(gw, entries):
    for key, (_, val) in entries:
        gw.opt.cache.put(key, val)


def test_alterar_uma_nota_nao_limpa_todo_o_cache(gw):
    gw.opt.ensure_fresh(gw)                      # fixa o manifesto
    _seed_cache(gw, [_entry({"pasta1/cao.md": "h"}, "cao passear"),
                     _entry({"pasta0/gato.md": "h"}, "gato recife")])
    assert gw.opt.cache.stats()["entries"] == 2
    p = gw.vault.root / "pasta0" / "gato.md"
    p.write_text("# Gato\n\no gato mudou para Olinda\n", encoding="utf-8")
    _bump(p)
    m = gw.opt.ensure_fresh(gw)
    assert m["index_rebuilt"] and m["index_incremental"] is True
    st = gw.opt.cache.stats()
    assert st["entries"] == 1 and st["selective_evictions"] == 1   # só a entrada do gato caiu
    assert gw.opt.index_rebuilds == 1


def test_nota_nova_que_casa_termo_derruba_so_entradas_afetadas(gw):
    gw.opt.ensure_fresh(gw)
    _seed_cache(gw, [_entry({"pasta1/cao.md": "h"}, "cao passear"),
                     _entry({"pasta0/gato.md": "h"}, "gato recife")])
    _note(gw.vault.root / "pasta2" / "novo.md", "Novo", "o CÃO de Joana também passeia")  # casa 'cao' (sem acento)
    m = gw.opt.ensure_fresh(gw)
    assert m["index_incremental"] is True and m["cache_dropped"] == 1 and m["cache_kept"] == 1


def test_indice_incremental_equivale_ao_rebuild_completo(gw):
    gw.opt.ensure_fresh(gw)
    root = gw.vault.root
    (root / "pasta1" / "cao.md").unlink()
    _note(root / "pasta2" / "novo.md", "Peixe", "o peixe vive no aquario de Natal")
    p = root / "pasta0" / "n3.md"
    p.write_text("# Nota 3\n\nagora fala de zebra\n", encoding="utf-8")
    _bump(p)
    assert gw.opt.ensure_fresh(gw)["index_incremental"] is True
    full = BaselineIndex(gw.vault)
    full.build()
    for q in ("peixe aquario", "zebra", "cao passear", "alfa comum", "gato recife"):
        a = sorted((c.source_file, c.section, c.snippet) for c in gw.baseline.search(q))
        b = sorted((c.source_file, c.section, c.snippet) for c in full.search(q))
        assert a == b, q
    assert gw.baseline.files_indexed == full.files_indexed
    assert gw.baseline.sections_indexed == full.sections_indexed


def test_mudanca_grande_cai_no_rebuild_completo_e_limpa_cache(gw):
    gw.opt.ensure_fresh(gw)
    _seed_cache(gw, [_entry({"pasta1/cao.md": "h"}, "cao passear")])
    for i in range(12):                           # >25% das notas
        _note(gw.vault.root / "extra" / f"x{i}.md", f"X{i}", "texto")
    m = gw.opt.ensure_fresh(gw)
    assert m["index_rebuilt"] and m["index_incremental"] is False
    assert gw.opt.cache.stats()["entries"] == 0


def test_sem_mudanca_nao_reindexa(gw):
    gw.opt.ensure_fresh(gw)
    assert gw.opt.ensure_fresh(gw)["index_rebuilt"] is False
    assert gw.opt.index_rebuilds == 0


def test_latencia_do_manifesto_vs_fingerprint(tmp_path):
    v = tmp_path / "big"
    for i in range(1500):
        _note(v / f"d{i % 40}" / f"n{i}.md", f"N{i}", "x")
    vault = ObsidianVault(v)
    t = time.perf_counter(); vault.fingerprint(); old = time.perf_counter() - t
    t = time.perf_counter(); scan_manifest(vault); new = time.perf_counter() - t
    assert new < old * 1.5     # nunca pior que o caminho antigo (ganho real medido em docs/bench/anam018_*.md)


def test_diff_detecta_add_change_remove():
    d = diff_manifests({"a": (1, 1), "b": (1, 1), "c": (1, 1)}, {"a": (1, 1), "b": (2, 1), "d": (1, 1)})
    assert (d.added, d.changed, d.removed) == (["d"], ["b"], ["c"])

"""ANA-102: incremental persistent FTS index (flag off by default)."""
import os

from app.retrieval.incremental_index import IncrementalBaselineIndex, make_baseline_index
from app.retrieval.baseline import BaselineIndex
from app.services.obsidian import ObsidianVault


def _vault(tmp_path, n=6):
    v = tmp_path / "vault"
    v.mkdir()
    for i in range(n):
        (v / f"n{i}.md").write_text(f"# Nota {i}\n\nconteudo alfa{i} comum zebra\n\n## Sub\n\ntexto beta{i}\n", encoding="utf-8")
    return v


def _key(cands):
    return sorted((c.source_file, c.section, round(c.score, 6)) for c in cands)


def test_flag_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("MG_INCREMENTAL_INDEX", raising=False)
    v = ObsidianVault(_vault(tmp_path))
    assert type(make_baseline_index(v, tmp_path / "i.db")) is BaselineIndex
    monkeypatch.setenv("MG_INCREMENTAL_INDEX", "1")
    assert isinstance(make_baseline_index(v, tmp_path / "i.db"), IncrementalBaselineIndex)


def test_parity_with_memory_index(tmp_path):
    v = ObsidianVault(_vault(tmp_path))
    mem = BaselineIndex(v)
    inc = IncrementalBaselineIndex(v, tmp_path / "idx" / "i.db")
    for q in ("zebra", "alfa3", "beta1 comum"):
        assert _key(mem.search(q)) == _key(inc.search(q))
    assert inc.last_stats["reindexed"] == 6


def test_warm_start_reindexes_nothing_and_changes_are_proportional(tmp_path):
    root = _vault(tmp_path)
    v = ObsidianVault(root)
    db = tmp_path / "i.db"
    IncrementalBaselineIndex(v, db).build()
    inc = IncrementalBaselineIndex(v, db)  # new process analogue: persisted file reused
    inc.build()
    assert inc.last_stats["reindexed"] == 0 and inc.last_stats["unchanged"] == 6

    p = root / "n2.md"
    p.write_text("# Nota 2\n\nnovidade quokka\n", encoding="utf-8")
    inc.build()
    assert inc.last_stats["reindexed"] == 1 and inc.last_stats["unchanged"] == 5
    assert inc.search("quokka") and not inc.search("alfa2")
    assert inc.search("alfa3") and inc.search("beta4") and inc.search("beta1")  # neighbours untouched

    p.unlink()
    inc.build()
    assert inc.last_stats["removed"] == 1 and not inc.search("quokka")


def test_touch_without_content_change_skips_reindex(tmp_path):
    root = _vault(tmp_path)
    v = ObsidianVault(root)
    inc = IncrementalBaselineIndex(v, tmp_path / "i.db")
    inc.build()
    p = root / "n1.md"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    inc.build()
    assert inc.last_stats["touched_same_hash"] == 1 and inc.last_stats["reindexed"] == 0

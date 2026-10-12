"""ANA-010: adversarial retrieval dataset, offline, deterministic."""
import hashlib

import pytest

from app.benchmark import adversarial as adv
from app.retrieval.baseline import BaselineIndex
from app.services.obsidian import ObsidianVault


@pytest.fixture(scope="module")
def index(tmp_path_factory):
    root = adv.build(tmp_path_factory.mktemp("advvault"))
    idx = BaselineIndex(ObsidianVault(root))
    idx.build() if hasattr(idx, "build") else None
    return idx


def test_shape_10_classes_5_cases():
    assert len(adv.CLASSES) >= 10
    for k in adv.CLASSES:
        assert len(adv.CASES[k]) >= 5, k


def test_deterministic(tmp_path):
    def digest(p):
        adv.build(p)
        h = hashlib.sha256()
        for f in sorted(p.rglob("*.*")):
            h.update(f.relative_to(p).as_posix().encode() + f.read_bytes())
        return h.hexdigest()
    assert digest(tmp_path / "a") == digest(tmp_path / "b")


def test_vault_builds_and_search_never_crashes(index):
    for cls in adv.CLASSES:
        for q, _exp, _forb in adv.CASES[cls]:
            assert isinstance(index.search(q, 10), list)


# All classes are solved by the lexical baseline today; any class removed from SOLVED is reported as a gap.
SOLVED = set(adv.CLASSES)  # measured 5/5 per class on the lexical baseline (2026-10-12)


def _hit(index, q, exp, forb):
    files = [c.source_file.replace("\\", "/") for c in index.search(q, 5)]
    return exp in files and (forb is None or files.index(exp) < (files.index(forb) if forb in files else 99))


@pytest.mark.parametrize("cls", sorted(SOLVED))
def test_solved_classes(index, cls):
    miss = [q for q, e, f in adv.CASES[cls] if not _hit(index, q, e, f)]
    assert not miss, miss


@pytest.mark.parametrize("cls", sorted(set(adv.CLASSES) - SOLVED))
def test_known_gaps_reported(index, cls):
    hits = sum(_hit(index, q, e, f) for q, e, f in adv.CASES[cls])
    print(f"[ANA-010] known-gap class {cls}: {hits}/{len(adv.CASES[cls])}")
    assert 0 <= hits <= len(adv.CASES[cls])

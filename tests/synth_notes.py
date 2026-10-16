"""Corpus sintético determinístico para ANAM-008/011: notas salvas com duplicatas PLANTADAS.

Escreve os arquivos direto (render + write), sem passar por save() (que faz fsync + lock por nota e
levaria minutos com milhares de notas). Devolve o ground truth dos grupos de duplicatas.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.memory_store.store import SavedNote, content_digest, render, slugify

_VOCAB = [f"w{n:04d}x" for n in range(4000)]
_AGENTS = ("claude", "codex", "hermes", "mcp")
_PROJECTS = ("alfa", "beta", "gama", "delta", None)


def _text(rng: random.Random, n_tokens: int) -> list[str]:
    return [rng.choice(_VOCAB) for _ in range(n_tokens)]


def _near_variant(rng: random.Random, toks: list[str]) -> list[str]:
    """Troca ~2% dos tokens: similaridade de sequência >= 0.95 (acima do limiar 0.92)."""
    out = list(toks)
    for _ in range(max(1, len(out) // 50)):
        out[rng.randrange(len(out))] = rng.choice(_VOCAB)
    return out


def _far_variant(rng: random.Random, toks: list[str]) -> list[str]:
    """Troca ~25% dos tokens: parecida, mas ABAIXO do limiar (nao pode agrupar)."""
    out = list(toks)
    for i in rng.sample(range(len(out)), max(2, len(out) // 4)):
        out[i] = rng.choice(_VOCAB)
    return out


def make_corpus(root: Path | str, n_notes: int = 3000, *, dup_groups: int = 60, near_miss: int = 40,
                seed: int = 7, tokens: int = 100) -> dict:
    """Cria `n_notes` arquivos em `root`. Retorna {"ids": [...], "dup_groups": [[ids...]], "near_miss": [[a,b]]}."""
    rng = random.Random(seed)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bodies: list[tuple[str, list[str], str | None, str | None]] = []  # (title, tokens, project, agent)

    def add(title, toks, project=None, agent=None):
        bodies.append((title, toks, project if project is not None else rng.choice(_PROJECTS),
                       agent or rng.choice(_AGENTS)))
        return len(bodies) - 1

    groups_idx: list[list[int]] = []
    miss_idx: list[list[int]] = []
    for g in range(dup_groups):
        toks = _text(rng, tokens)
        project = rng.choice(_PROJECTS)
        idxs = [add(f"Duplicada {g} v0", toks, project)]
        for v in range(1, 2 + g % 3):  # grupos de 2 a 4
            idxs.append(add(f"Duplicada {g} v{v}", _near_variant(rng, toks), project))
        groups_idx.append(idxs)
    for m in range(near_miss):
        toks = _text(rng, tokens)
        miss_idx.append([add(f"Quase {m} a", toks), add(f"Quase {m} b", _far_variant(rng, toks))])
    while len(bodies) < n_notes:
        k = len(bodies)
        add(f"Nota avulsa {k}", _text(rng, tokens))
    order = list(range(len(bodies)))
    rng.shuffle(order)  # duplicatas espalhadas, nao adjacentes

    ids: dict[int, str] = {}
    for pos, i in enumerate(order):
        title, toks, project, agent = bodies[i]
        nid = f"{(seed * 100003 + pos * 7919 + 0xA00000000) & 0xFFFFFFFFFF:010x}"
        content = " ".join(toks)
        ts = (base + timedelta(seconds=pos)).astimezone().isoformat(timespec="seconds")
        note = SavedNote(nid, title, content, project, ["t1", "t2"], agent, ts, ts, f"{slugify(title)}-{nid}.md",
                         "untrusted", schema=2, kind="fact", status="active", source=f"agent:{agent}",
                         content_sha256=content_digest(content))
        (root / note.file).write_text(render(note), encoding="utf-8", newline="\n")
        ids[i] = nid
    return {"ids": [ids[i] for i in range(len(bodies))],
            "dup_groups": [[ids[i] for i in g] for g in groups_idx],
            "near_miss": [[ids[i] for i in g] for g in miss_idx]}

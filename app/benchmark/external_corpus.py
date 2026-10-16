"""ANA-113: loader for externally-authored, independently-annotated evaluation corpora.

Layout (one directory per corpus):
  manifest.json : {"name","version","author","author_kind":"human|llm","generator":"<model or ''>",
                   "annotators":["A","B"],"items_sha256":"<sha256 of items.jsonl bytes>"}
  items.jsonl   : one JSON per line: {"id","question","answerable":bool,
                   "candidates":[{"source":"rel/path.md","labels":{"A":"relevant","B":"not_relevant"}}]}

`load()` verifies the integrity hash (CorpusIntegrityError on any drift). Metrics are reported PER
CORPUS: there is deliberately no function that merges corpora (ANA-113: synthetic and independent
numbers are not comparable). No real corpus ships with the repo: it needs a human author and two
annotators (see docs/reports/ANA109_ANA113_LABELING_INFRA.md).

LIMITATION (AUD-057): the corpora shipped/used by the benchmarks today (benchmark/questions.json,
benchmark/routing_tasks*.json) are SYNTHETIC -- written/derived by the same team (or an LLM) that tunes the
retrieval/routing, so scores on them are optimistic and say nothing about unseen real vaults. They are good
for regression detection (same corpus, before x after), NOT for absolute claims. Absolute quality claims
require an external corpus (human author + >=2 independent annotators, kappa reported) loaded here, and
reported separately. See docs/bench/anam025_rigor_power.md.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.benchmark.labeling import LABELS, cohen_kappa


class CorpusIntegrityError(RuntimeError):
    """items.jsonl differs from the hash recorded in the manifest, or the manifest/items are malformed."""


@dataclass
class ExternalCorpus:
    name: str
    version: str
    author_kind: str
    generator: str
    annotators: list[str]
    items_sha256: str
    items: list[dict] = field(default_factory=list)

    def adjudicated_relevant(self, item: dict) -> set[str]:
        """Sources every annotator marked relevant (unanimous) -- the strict ground truth."""
        return {c["source"] for c in item.get("candidates", [])
                if all(c.get("labels", {}).get(a) == "relevant" for a in self.annotators)}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_manifest(directory: Path | str, *, name: str, version: str, author: str, author_kind: str,
                   annotators: list[str], generator: str = "") -> dict:
    """Helper for the human who builds the corpus: freezes the hash of items.jsonl into manifest.json."""
    d = Path(directory)
    m = {"name": name, "version": version, "author": author, "author_kind": author_kind,
         "generator": generator, "annotators": annotators, "items_sha256": sha256_file(d / "items.jsonl")}
    (d / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return m


def load(directory: Path | str) -> ExternalCorpus:
    d = Path(directory)
    try:
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        raw = (d / "items.jsonl").read_bytes()
    except (OSError, ValueError) as exc:
        raise CorpusIntegrityError(f"corpus ilegível em {d}: {exc}") from None
    for key in ("name", "version", "annotators", "items_sha256", "author_kind"):
        if key not in m:
            raise CorpusIntegrityError(f"manifest sem campo {key!r}")
    got = hashlib.sha256(raw).hexdigest()
    if got != m["items_sha256"]:
        raise CorpusIntegrityError(f"hash de items.jsonl {got[:12]} != manifest {m['items_sha256'][:12]}: "
                                   "itens alterados; congele nova versão")
    if len(m["annotators"]) < 2:
        raise CorpusIntegrityError("ANA-113 exige >= 2 anotadores independentes")
    try:
        items = [json.loads(ln) for ln in raw.decode("utf-8").splitlines() if ln.strip()]
    except ValueError as exc:
        raise CorpusIntegrityError(f"items.jsonl inválido: {exc}") from None
    ids = [str(i.get("id")) for i in items]
    if len(set(ids)) != len(ids):
        raise CorpusIntegrityError("ids duplicados em items.jsonl")
    for it in items:
        for c in it.get("candidates", []):
            for a, lab in c.get("labels", {}).items():
                if lab not in LABELS:
                    raise CorpusIntegrityError(f"item {it.get('id')}: rótulo inválido {lab!r} de {a}")
    return ExternalCorpus(m["name"], str(m["version"]), m["author_kind"], m.get("generator", ""),
                          list(m["annotators"]), m["items_sha256"], items)


def annotator_agreement(corpus: ExternalCorpus) -> dict:
    """Cohen's kappa between the first two annotators over candidates both labelled."""
    a, b = corpus.annotators[:2]
    la, lb = [], []
    for it in corpus.items:
        for c in it.get("candidates", []):
            lab = c.get("labels", {})
            if a in lab and b in lab:
                la.append(lab[a])
                lb.append(lab[b])
    return {"annotators": [a, b], **cohen_kappa(la, lb)}


def evaluate(corpus: ExternalCorpus, retrieve: Callable[[str], list[str]], k: int = 5) -> dict:
    """hit@k and MRR of `retrieve(question) -> ranked source list` against the unanimous relevant set.
    Answerable questions without any unanimous relevant source are excluded (and counted)."""
    hits = rr = n = skipped = 0
    for it in corpus.items:
        if not it.get("answerable", True):
            continue
        rel = corpus.adjudicated_relevant(it)
        if not rel:
            skipped += 1
            continue
        ranked = list(retrieve(it["question"]))
        n += 1
        pos = next((i for i, s in enumerate(ranked, 1) if s in rel), None)
        if pos is not None and pos <= k:
            hits += 1
        if pos is not None:
            rr += 1.0 / pos
    return {"n_questions": n, "skipped_no_consensus": skipped, "k": k,
            f"hit@{k}": round(hits / n, 4) if n else "UNKNOWN", "mrr": round(rr / n, 4) if n else "UNKNOWN"}


def report(corpus: ExternalCorpus, retrieve: Callable[[str], list[str]] | None = None, k: int = 5) -> dict:
    """One corpus -> one report. Never combined with other corpora."""
    rep = {"corpus": corpus.name, "version": corpus.version, "items_sha256": corpus.items_sha256,
           "author_kind": corpus.author_kind, "generator": corpus.generator,
           "n_questions": len(corpus.items), "agreement": annotator_agreement(corpus)}
    if retrieve is not None:
        rep["metrics"] = evaluate(corpus, retrieve, k)
    return rep


def report_per_corpus(corpora: list[ExternalCorpus], retrieve: Callable[[str], list[str]] | None = None,
                      k: int = 5) -> dict[str, dict]:
    """{corpus name: report}. Keys are corpora; there is intentionally no 'overall' entry (ANA-113)."""
    out: dict[str, dict] = {}
    for c in corpora:
        key = f"{c.name}@{c.version}"
        if key in out:
            raise ValueError(f"corpus duplicado {key}")
        out[key] = report(c, retrieve, k)
    return out

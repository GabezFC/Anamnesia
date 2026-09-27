"""PIPELINE A retriever — deterministic lexical search (§9).

Implementation: in-memory SQLite FTS5 index over heading-delimited sections of every note,
tokenizer `unicode61 remove_diacritics 2` (accent-insensitive), ranked by FTS5 `bm25()`.
Query terms are lower-cased, stop-words removed and OR-combined. No Graphify, no JEV, no embeddings.
"""
from __future__ import annotations

import re
import sqlite3
import threading

from app.schemas.models import Candidate
from app.services.obsidian import ObsidianVault, frontmatter_status, split_sections

STOPWORDS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por pelo pela pelos pelas para pra com sem
e ou que qual quais quando como onde porque porquê se ser foi era é são está estão meu minha meus minhas
seu sua seus suas nosso nossa isso isto esse essa este esta aquele aquela ao aos à às the of and to in
is are was what how why which who for on with be it this that my me eu você voce ele ela lhe mais menos
já ja ainda sobre entre até ate também tambem foram tem ter há ha fazer feito sido
""".split())
_TOKEN = re.compile(r"[\wÀ-ÿ\-]+", re.U)


def query_terms(query: str) -> list[str]:
    terms = []
    for t in _TOKEN.findall(query.lower()):
        t = t.strip("-")
        if len(t) < 2 or t in STOPWORDS:
            continue
        if t not in terms:
            terms.append(t)
    return terms


class BaselineIndex:
    def __init__(self, vault: ObsidianVault):
        self.vault = vault
        self._lock = threading.Lock()
        self.conn: sqlite3.Connection | None = None
        self.sections_indexed = 0
        self.files_indexed = 0

    def build(self) -> None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute(
            "CREATE VIRTUAL TABLE sec USING fts5(file UNINDEXED, section, body, status UNINDEXED, line UNINDEXED,"
            " tokenize = 'unicode61 remove_diacritics 2')"
        )
        files = self.vault.list_markdown()
        n = 0
        for rel in files:
            text = self.vault.read(rel)
            status = frontmatter_status(text) or ""
            for s in split_sections(text):
                conn.execute("INSERT INTO sec VALUES (?,?,?,?,?)", (rel, s.heading_path, s.text, status, s.line))
                n += 1
        conn.commit()
        with self._lock:
            self.conn = conn
            self.sections_indexed = n
            self.files_indexed = len(files)

    def search(self, query: str, limit: int = 100) -> list[Candidate]:
        if self.conn is None:
            self.build()
        terms = query_terms(query)
        if not terms:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        with self._lock:
            rows = self.conn.execute(
                # section column weighted 2x body; archived notes are demoted by rank, never hidden.
                "SELECT file, section, body, status, line, bm25(sec, 2.0, 1.0) AS r FROM sec WHERE sec MATCH ?"
                " ORDER BY r LIMIT ?",
                (match, limit),
            ).fetchall()
        out = []
        for i, (file, section, body, status, line, r) in enumerate(rows):
            score = -float(r)  # bm25() is lower-is-better
            if status == "arquivado":
                score *= 0.5
            out.append(Candidate(
                candidate_id=f"b{i:03d}:{file}#L{line}",
                source_file=file, section=section, snippet=body, score=score, origin="baseline",
                meta={"line": line, "status": status},
            ))
        out.sort(key=lambda c: -c.score)
        return out

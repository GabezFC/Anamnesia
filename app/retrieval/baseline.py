"""PIPELINE A retriever — deterministic lexical search (§9).

Implementation: in-memory SQLite FTS5 index over heading-delimited sections of every note,
tokenizer `unicode61 remove_diacritics 2` (accent-insensitive), ranked by FTS5 `bm25()`.
Query terms are lower-cased, stop-words removed and OR-combined. No Graphify, no JEV, no embeddings.
"""
from __future__ import annotations

import re
import sqlite3
import threading

from app.retrieval.experiments import bm25_expr
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
        files = self.vault.list_searchable()
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

    def search(self, query: str, limit: int = 100, exp=None, scope=None) -> list[Candidate]:
        """`exp`/`scope` are the Onda 9 experiment hooks (app/retrieval/experiments.py). Both None == the
        legacy query, unchanged (ANA-226: its `bm25(sec, 2.0, 1.0)` weighted the UNINDEXED `file` column)."""
        if self.conn is None:
            self.build()
        if exp is not None:
            return self._search_experimental(query, limit, exp, scope)
        terms = query_terms(query)
        if not terms:
            return []
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        with self._lock:
            rows = self.conn.execute(
                # ANA-226: weights are per column in table order (file, section, body, ...). The old
                # `bm25(sec, 2.0, 1.0)` gave 2.0 to the UNINDEXED `file` column and 1.0 to `section` (no
                # heading boost at all); bm25_expr() puts the weight on `section`. Archived notes are demoted
                # by rank, never hidden.
                f"SELECT file, section, body, status, line, {bm25_expr(None)} AS r FROM sec WHERE sec MATCH ?"
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

    def _search_experimental(self, query: str, limit: int, exp, scope) -> list[Candidate]:
        from app.retrieval.experiments import bm25_expr, fts_match
        match = fts_match(query, exp, query_terms)
        if not match:
            return []
        sql = (f"SELECT file, section, body, status, line, {bm25_expr(exp)} AS r FROM sec WHERE sec MATCH ?"
               " ORDER BY r")
        with self._lock:
            cur = self.conn.execute(sql, (match,))
            if scope is not None and not scope.is_global:   # ANA-227: scope BEFORE the top-N cut
                rows = []
                for row in cur:
                    if scope.matches(row[0]):
                        rows.append(row)
                        if len(rows) >= limit:
                            break
            else:
                rows = cur.fetchmany(limit)
        out = []
        for i, (file, section, body, status, line, r) in enumerate(rows):
            score = -float(r)
            if status == "arquivado":
                score *= 0.5
            out.append(Candidate(
                candidate_id=f"b{i:03d}:{file}#L{line}",
                source_file=file, section=section, snippet=body, score=score, origin="baseline",
                meta={"line": line, "status": status},
            ))
        out.sort(key=lambda c: -c.score)
        return out

    def count(self, query: str) -> int:
        """Candidate count for the SAME FTS5 match `search()` uses, without materializing rows or
        applying a limit. Cheap, deterministic size estimate for the verdict router
        (app/services/verdict.py) -- no judge, no model call."""
        if self.conn is None:
            self.build()
        terms = query_terms(query)
        if not terms:
            return 0
        match = " OR ".join('"' + t.replace('"', "") + '"' for t in terms)
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM sec WHERE sec MATCH ?", (match,)).fetchone()
        return row[0] if row else 0

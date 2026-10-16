"""ANAM-008 / AUD-026, AUD-028: catálogo SQLite DERIVADO das notas salvas.

O Markdown continua sendo a fonte da verdade. `memory.db` (em `<root>_state/`, separado do
`benchmark.db`) guarda, por arquivo de nota, `(mtime_ns, size, sha256)` e o registro já parseado, para que
`list()/get()/find_similar()` não leiam nem parseiem todos os arquivos a cada chamada.

  * atualização incremental: `sync()` faz um `scandir` (só stat) e reparseia apenas os arquivos cujo
    `(mtime_ns, size)` mudou; se o sha256 do conteúdo não mudou, só atualiza o mtime;
  * apagar o `memory.db` é seguro: o próximo uso reconstrói tudo (`rebuild()`), com resultados idênticos;
  * `verify()` confere catálogo x arquivos (hash completo) e reporta divergências, sem alterar nada;
  * qualquer erro do SQLite cai para a leitura direta dos arquivos (o catálogo nunca derruba o store).

CLI: `python -m app.memory_store.catalog {rebuild|verify|stats} [--root PASTA]`.
Desligar: MG_MEMORY_CATALOG=0.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import asdict, fields
from pathlib import Path

SCHEMA = 2
_DDL = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS notes (
    file TEXT PRIMARY KEY, id TEXT NOT NULL, mtime_ns INTEGER NOT NULL, size INTEGER NOT NULL,
    sha256 TEXT NOT NULL, project TEXT, kind TEXT, status TEXT, source_agent TEXT, trust TEXT, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS notes_id ON notes(id);
CREATE INDEX IF NOT EXISTS notes_agent ON notes(source_agent);
"""


def _store_mod():
    from app.memory_store import store  # import tardio: store importa este módulo
    return store


def _to_note(data: str):
    cls = _store_mod().SavedNote
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in json.loads(data).items() if k in names})


class NoteCatalog:
    def __init__(self, root: Path | str, db_path: Path | str):
        self.root = Path(root)
        self.db_path = Path(db_path)

    # -- infra ----------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(_DDL)
        row = con.execute("SELECT v FROM meta WHERE k='schema'").fetchone()
        if row is None:
            con.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (str(SCHEMA),))
        elif row[0] != str(SCHEMA):  # catálogo de outra versão: derivado, então descarta e refaz
            con.execute("DELETE FROM notes")
            con.execute("INSERT OR REPLACE INTO meta VALUES('schema', ?)", (str(SCHEMA),))
        return con

    def _scan(self) -> dict[str, tuple[str, int, int]]:
        """{arquivo: (id, mtime_ns, size)} -- só stat, sem ler conteúdo."""
        out: dict[str, tuple[str, int, int]] = {}
        if not self.root.is_dir():
            return out
        name_re = _store_mod()._NAME_RE
        with os.scandir(self.root) as it:
            for e in it:
                m = name_re.match(e.name)
                if m and e.is_file():
                    st = e.stat()
                    out[e.name] = (m.group(1), st.st_mtime_ns, st.st_size)
        return out

    def _read(self, name: str):
        """(sha256, SavedNote, mtime_ns, size) lendo o arquivo; None se sumiu/ilegível/sem frontmatter."""
        p = self.root / name
        try:
            st = p.stat()
            raw = p.read_bytes()
            note = _store_mod().parse(raw.decode("utf-8"), name)
        except (OSError, ValueError, _store_mod().SavedContextError):
            return None
        return hashlib.sha256(raw).hexdigest(), note, st.st_mtime_ns, st.st_size

    @staticmethod
    def _row(name, id_, mtime_ns, size, sha, note) -> tuple:
        return (name, id_, mtime_ns, size, sha, note.project, note.kind, note.status, note.source_agent,
                note.trust, json.dumps(asdict(note), ensure_ascii=False))

    # -- sincronização incremental ----------------------------------------------------------
    def sync(self) -> dict:
        """Alinha o catálogo ao disco. Retorna {scanned, reparsed, touched, removed}."""
        scan = self._scan()
        with closing(self._connect()) as con:
            have = {r[0]: (r[1], r[2], r[3], r[4]) for r in
                    con.execute("SELECT file, id, mtime_ns, size, sha256 FROM notes")}
            gone = [f for f in have if f not in scan]
            todo = [f for f, (i, mt, sz) in scan.items() if f not in have or have[f][:3] != (i, mt, sz)]
            reparsed = touched = 0
            con.execute("BEGIN IMMEDIATE")
            try:
                for f in gone:
                    con.execute("DELETE FROM notes WHERE file=?", (f,))
                for f in todo:
                    got = self._read(f)
                    if got is None:
                        con.execute("DELETE FROM notes WHERE file=?", (f,))
                        continue
                    sha, note, mt, sz = got
                    if f in have and have[f][3] == sha:  # só o mtime mudou
                        con.execute("UPDATE notes SET mtime_ns=?, size=? WHERE file=?", (mt, sz, f))
                        touched += 1
                        continue
                    con.execute("INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                self._row(f, scan[f][0], mt, sz, sha, note))
                    reparsed += 1
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        return {"scanned": len(scan), "reparsed": reparsed, "touched": touched, "removed": len(gone)}

    # -- consultas --------------------------------------------------------------------------
    def notes(self, project: str | None = None, kind: str | None = None) -> list:
        self.sync()
        sql, args = "SELECT data FROM notes", []
        cond = []
        if project:
            cond.append("project=?")
            args.append(project)
        if kind:
            cond.append("kind=?")
            args.append(kind)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        with closing(self._connect()) as con:
            rows = con.execute(sql + " ORDER BY file", args).fetchall()
        return [_to_note(r[0]) for r in rows]

    def get(self, note_id: str):
        """SavedNote do catálogo se o arquivo continua igual (stat); reparseia só esse arquivo se mudou;
        None se o id não está no catálogo ou o arquivo sumiu (o chamador cai para a leitura direta)."""
        with closing(self._connect()) as con:
            row = con.execute("SELECT file, mtime_ns, size, data FROM notes WHERE id=? ORDER BY file LIMIT 1",
                              (note_id,)).fetchone()
            if row is None:
                return None
            try:
                st = (self.root / row[0]).stat()
            except OSError:
                return None
            if (st.st_mtime_ns, st.st_size) == (row[1], row[2]):
                return _to_note(row[3])
            got = self._read(row[0])
            if got is None:
                return None
            sha, note, mt, sz = got
            con.execute("INSERT OR REPLACE INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        self._row(row[0], note_id, mt, sz, sha, note))
            return note

    def trust_map(self) -> dict[str, tuple[str | None, str | None]]:
        """{arquivo: (trust, status)} -- usado pelo retrieval para rebaixar/segregar notas não confiáveis."""
        self.sync()
        with closing(self._connect()) as con:
            return {r[0]: (r[1], r[2]) for r in con.execute("SELECT file, trust, status FROM notes")}

    def path_of(self, note_id: str) -> Path | None:
        """Caminho do arquivo da nota segundo o catálogo, se o arquivo ainda existe (senão None)."""
        with closing(self._connect()) as con:
            row = con.execute("SELECT file FROM notes WHERE id=? ORDER BY file LIMIT 1", (note_id,)).fetchone()
        p = self.root / row[0] if row else None
        return p if p is not None and p.is_file() else None

    def count_by_agent(self, agent: str) -> int:
        self.sync()
        with closing(self._connect()) as con:
            return con.execute("SELECT COUNT(*) FROM notes WHERE source_agent=?", (agent,)).fetchone()[0]

    # -- manutenção ---------------------------------------------------------------------------
    def rebuild(self) -> dict:
        """Descarta o catálogo e reconstrói do Markdown."""
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(str(self.db_path) + suffix)
            except FileNotFoundError:
                pass
        return self.sync()

    def verify(self) -> dict:
        """Compara o catálogo com o disco (hash completo). Não altera nada."""
        scan = self._scan()
        with closing(self._connect()) as con:
            have = {r[0]: (r[1], r[2]) for r in con.execute("SELECT file, sha256, data FROM notes")}
        missing = sorted(f for f in scan if f not in have)
        extra = sorted(f for f in have if f not in scan)
        mismatch = []
        for f in sorted(set(scan) & set(have)):
            got = self._read(f)
            if got is None or got[0] != have[f][0] or asdict(got[1]) != json.loads(have[f][1]):
                mismatch.append(f)
        return {"ok": not (missing or extra or mismatch), "files": len(scan), "catalog_rows": len(have),
                "missing_in_catalog": missing, "extra_in_catalog": extra, "mismatch": mismatch}


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m app.memory_store.catalog")
    ap.add_argument("cmd", choices=("rebuild", "verify", "stats"))
    ap.add_argument("--root", help="pasta saved_context (padrão: a do usuário)")
    a = ap.parse_args(argv)
    from app.memory_store.store import SavedContextStore
    store = SavedContextStore(a.root) if a.root else SavedContextStore()
    cat = store.catalog or NoteCatalog(store.root, store.state_dir / "memory.db")
    res = {"rebuild": cat.rebuild, "verify": cat.verify, "stats": cat.sync}[a.cmd]()
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())

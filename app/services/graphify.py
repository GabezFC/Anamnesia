"""Graphify adapter (§9 PIPELINE B). Verified against graphify 0.9.59 CLI — see Cérebro IA (Anamnesia/Guias-de-usuario-2026-10-24/ENVIRONMENT.md).

Graphify writes `graphify-out/` inside the analysed directory, so it must never run on the vault.
We keep a byte-identical mirror of the vault's markdown in `data/vault_mirror/` (copied through the
read-only ObsidianVault) and build the graph there with `graphify update` (AST only, no LLM).

Query: `graphify query "<q>" --budget N --graph <graph.json>` prints
    Graph: ... | Start: ['label', ...] | K nodes found
    NODE <label> [src=<file> loc=L<n> community=<...>]
    EDGE ...
The CLI exposes no numeric relevance; graph_score is derived from traversal order:
seed nodes ('Start') get 1.0; other nodes decay linearly with BFS order down to 0.3.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from app.schemas.models import Candidate
from app.services.obsidian import ObsidianVault, split_sections

_NODE = re.compile(r"^NODE (?P<label>.+?) \[src=(?P<src>.+?) loc=L(?P<line>\d+)(?: community=(?P<comm>.*))?\]\s*$")
_START = re.compile(r"Start: (\[.*?\]) \|")


class GraphifyError(RuntimeError):
    pass


class GraphifyService:
    def __init__(self, vault: ObsidianVault, mirror_dir: Path, graphify_bin: str = "graphify",
                 query_budget: int = 6000, timeout_s: int = 60,
                 stale_fallback_s: float = 0.0):
        self.vault = vault
        self.mirror = Path(mirror_dir)
        self.bin = shutil.which(graphify_bin) or graphify_bin
        self.query_budget = query_budget
        self.timeout_s = timeout_s
        self._section_cache: dict[str, tuple[bytes, list]] = {}
        # ANA-080: graph staleness. stale_fallback_s > 0 => graph candidates are dropped (BM25-only)
        # once the graph has been stale for longer than that many seconds. 0 = never fall back.
        self.stale_fallback_s = float(stale_fallback_s)
        self._refresh_lock = threading.Lock()
        self._refresh_thread: threading.Thread | None = None
        self._stale_since: float | None = None

    @property
    def fp_path(self) -> Path:
        return self.mirror / "graphify-out" / "vault_fp.json"

    def _vault_fp(self) -> list | None:
        try:
            return json.loads(json.dumps(self.vault.fingerprint()))   # tuple -> list, JSON-comparable
        except Exception:  # noqa: BLE001 — advisory
            return None

    def _save_fp(self) -> None:
        fp = self._vault_fp()
        if fp is not None and self.graph_path.parent.exists():
            self.fp_path.write_text(json.dumps(fp), encoding="utf-8")

    def staleness(self) -> dict:
        """ANA-080: compare the vault fingerprint recorded at the last graph build with the current one.

        Stat-only (no content read). `graph_stale` is True when they differ, or when a graph exists
        without a recorded fingerprint (unknown provenance -> treat as stale).
        """
        if not self.graph_path.exists():
            return {"graph_stale": False, "graph_exists": False}
        try:
            built = json.loads(self.fp_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            built = None
        stale = built is None or built != self._vault_fp()
        if not stale:
            self._stale_since = None
        elif self._stale_since is None:
            self._stale_since = time.time()
        age = round(time.time() - self._stale_since, 1) if self._stale_since else 0.0
        return {"graph_stale": stale, "graph_exists": True, "graph_stale_age_s": age}

    def refresh_async(self) -> bool:
        """ANA-080: rebuild the graph (AST-only `graphify update`, no LLM) in a background thread.

        Single-flight: returns False when a refresh is already running.
        """
        if not self._refresh_lock.acquire(blocking=False):
            return False

        def _run() -> None:
            try:
                self.build()
            except Exception:  # noqa: BLE001 — a failed refresh keeps the old graph; stays stale
                pass
            finally:
                self._refresh_lock.release()

        self._refresh_thread = threading.Thread(target=_run, name="graphify-refresh", daemon=True)
        self._refresh_thread.start()
        return True

    @property
    def graph_path(self) -> Path:
        return self.mirror / "graphify-out" / "graph.json"

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    def version(self) -> str | None:
        try:
            r = subprocess.run([self.bin, "--version"], capture_output=True, timeout=20, env=self._env())
            return r.stdout.decode("utf-8", "replace").strip() or None
        except (OSError, subprocess.TimeoutExpired):
            return None

    # -- index ----------------------------------------------------------------
    def sync_mirror(self) -> dict[str, int]:
        """Copy vault markdown into the mirror (vault is only read). Returns change counts."""
        mirror = self.mirror.resolve()
        if mirror == self.vault.root or self.vault.root in mirror.parents or mirror in self.vault.root.parents:
            raise GraphifyError(f"mirror_dir não pode estar dentro do vault nem contê-lo: {mirror}")
        self.mirror.mkdir(parents=True, exist_ok=True)
        wanted = set(self.vault.list_markdown())
        changed = removed = 0
        for rel in wanted:
            data = self.vault.read(rel).encode("utf-8")
            dst = self.mirror / rel
            if dst.exists() and hashlib.sha256(dst.read_bytes()).digest() == hashlib.sha256(data).digest():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            changed += 1
        for p in self.mirror.rglob("*.md"):
            rel = p.relative_to(self.mirror).as_posix()
            if rel.startswith("graphify-out/"):
                continue
            if rel not in wanted:
                p.unlink()
                removed += 1
        self._section_cache.clear()
        return {"files": len(wanted), "changed": changed, "removed": removed}

    def build(self, force: bool = False) -> dict:
        stats = self.sync_mirror()
        if stats["changed"] or stats["removed"] or force or not self.graph_path.exists():
            t0 = time.perf_counter()
            args = [self.bin, "update", str(self.mirror)]
            if force or stats["removed"]:
                args.append("--force")
            r = subprocess.run(args, capture_output=True, timeout=600, env=self._env(), cwd=str(self.mirror))
            stats["build_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            if r.returncode != 0 or not self.graph_path.exists():
                raise GraphifyError(r.stderr.decode("utf-8", "replace")[-800:])
        self._save_fp()   # ANA-080: remember which vault state this graph was built from
        self._stale_since = None
        stats["graph"] = str(self.graph_path)
        return stats

    # -- query ----------------------------------------------------------------
    def raw_query(self, query: str, budget: int | None = None) -> str:
        if not self.graph_path.exists():
            self.build()
        args = [self.bin, "query", query, "--budget", str(budget or self.query_budget), "--graph", str(self.graph_path)]
        r = subprocess.run(args, capture_output=True, timeout=self.timeout_s, env=self._env(), cwd=str(self.mirror))
        out = r.stdout.decode("utf-8", "replace")
        if r.returncode != 0 and "NODE" not in out:
            err = r.stderr.decode("utf-8", "replace")
            if "No matching nodes" in out + err:
                return ""
            raise GraphifyError(err[-800:] or out[-800:])
        return out

    @staticmethod
    def parse(output: str) -> tuple[list[dict], list[str]]:
        seeds: list[str] = []
        m = _START.search(output)
        if m:
            try:
                seeds = list(ast.literal_eval(m.group(1)))
            except (ValueError, SyntaxError):
                seeds = []
        nodes = []
        for line in output.splitlines():
            nm = _NODE.match(line.strip())
            if nm:
                nodes.append({"label": nm["label"], "src": nm["src"], "line": int(nm["line"]), "community": nm["comm"]})
        return nodes, seeds

    def _sections(self, rel: str):
        # Read through the confined vault API on every request. A stat-only key
        # misses same-size edits with preserved timestamps; hash the exact text
        # being split instead. This refreshes evidence, not graph topology/lines.
        try:
            text = self.vault.read(rel)
        except (OSError, ValueError):
            self._section_cache.pop(rel, None)
            raise
        signature = hashlib.sha256(text.encode("utf-8")).digest()
        cached = self._section_cache.get(rel)
        if cached is None or cached[0] != signature:
            cached = (signature, split_sections(text))
            self._section_cache[rel] = cached
        return cached[1]

    def _section_for(self, rel: str, line: int):
        secs = self._sections(rel)
        idx = 0
        for i, s in enumerate(secs):
            if s.line <= line:
                idx = i
            else:
                break
        if not secs:
            return None, ""
        sec = secs[idx]
        # A heading node whose own section has almost no body (e.g. the note's H1) is expanded with the
        # following sections so the candidate carries content. Deterministic; the snippet budget cuts it later.
        text = sec.text
        j = idx + 1
        while len(text.split("\n", 1)[-1].strip()) < 200 and j < len(secs):
            text += "\n\n" + secs[j].text
            j += 1
        return sec, text

    def search(self, query: str, limit: int = 100) -> tuple[list[Candidate], dict]:
        t0 = time.perf_counter()
        st = self.staleness()   # ANA-080
        if st["graph_stale"]:
            self.refresh_async()
        if st["graph_stale"] and self.stale_fallback_s > 0 and st["graph_stale_age_s"] >= self.stale_fallback_s:
            return [], {"graphify_latency_ms": 0.0, "graphify_nodes_returned": 0, "graphify_seeds": 0,
                        "graphify_truncated": False, "graph_stale": True, "graph_fallback": "bm25_only",
                        "graph_stale_age_s": st["graph_stale_age_s"]}
        out = self.raw_query(query)
        nodes, seeds = self.parse(out)
        cands: list[Candidate] = []
        dangling = 0   # ANA-080: graph nodes whose file/section no longer exists
        n = max(len(nodes), 1)
        for i, node in enumerate(nodes[:limit]):
            rel = node["src"].replace("\\", "/")
            if not rel.lower().endswith(".md"):
                continue
            try:
                sec, body = self._section_for(rel, node["line"])
            except (OSError, PermissionError):
                dangling += 1
                continue
            if sec is None:
                dangling += 1
                continue
            score = 1.0 if node["label"] in seeds else round(0.9 - 0.6 * (i / n), 4)
            cands.append(Candidate(
                candidate_id=f"g{i:03d}:{rel}#L{sec.line}",
                source_file=rel, section=sec.heading_path, snippet=body, score=score, origin="graphify",
                meta={"node_label": node["label"], "node_line": node["line"], "community": node["community"],
                      "seed": node["label"] in seeds},
            ))
        info = {"graphify_latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "graphify_nodes_returned": len(nodes), "graphify_seeds": len(seeds),
                "graphify_truncated": "TRUNCATED" in out,
                "graph_stale": st["graph_stale"], "graph_dangling_candidates": dangling,
                "graph_dangling_rate": round(dangling / n, 4) if nodes else 0.0}
        return cands, info

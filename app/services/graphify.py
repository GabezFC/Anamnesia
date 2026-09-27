"""Graphify adapter (§9 PIPELINE B). Verified against graphify 0.9.59 CLI — see docs/ENVIRONMENT.md.

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
import os
import re
import shutil
import subprocess
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
                 query_budget: int = 6000, timeout_s: int = 60):
        self.vault = vault
        self.mirror = Path(mirror_dir)
        self.bin = shutil.which(graphify_bin) or graphify_bin
        self.query_budget = query_budget
        self.timeout_s = timeout_s
        self._section_cache: dict[str, list] = {}

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
        if rel not in self._section_cache:
            self._section_cache[rel] = split_sections(self.vault.read(rel))
        return self._section_cache[rel]

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
        out = self.raw_query(query)
        nodes, seeds = self.parse(out)
        cands: list[Candidate] = []
        n = max(len(nodes), 1)
        for i, node in enumerate(nodes[:limit]):
            rel = node["src"].replace("\\", "/")
            if not rel.lower().endswith(".md"):
                continue
            try:
                sec, body = self._section_for(rel, node["line"])
            except (OSError, PermissionError):
                continue
            if sec is None:
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
                "graphify_truncated": "TRUNCATED" in out}
        return cands, info

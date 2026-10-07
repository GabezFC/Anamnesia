#!/usr/bin/env python
"""Publication-safety scanner: working tree AND full git history.

Looks for secrets, personal absolute paths, private-vault markers and files that must never be
published (.env, SQLite DBs, logs, vault mirrors, benchmark datasets derived from a private vault).

Design
- Stdlib only. Memory bounded: history is streamed from `git log --all -p` line by line (a line is
  truncated at MAX_LINE chars), and only ADDED lines are matched (a removed line was added earlier).
- Matched values are NEVER printed in full: secrets show a 4-char prefix + length, personal paths keep
  the directory part and 2 chars of the user name.
- Read-only: never modifies the repo or the working tree.

Usage
  python scripts/scan_publication_safety.py [--repo .] [--out-dir reports] [--max-locations 10]
                                            [--no-history] [--fail-on-findings]
Writes <out-dir>/publication_safety_report.json and .md (reports/ is gitignored) and prints the table.
Exit code: 0 clean (or no --fail-on-findings), 1 findings with --fail-on-findings.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

MAX_LINE = 2000          # truncate very long lines (minified files) to bound memory/CPU
MAX_FILE_BYTES = 2_000_000
LARGE_BYTES = 1_000_000

# Placeholder user names that are not personal data.
_PLACEHOLDER_USERS = {
    "public", "user", "users", "username", "name", "you", "me", "x", "xxx", "foo", "bar", "example",
    "runner", "runneradmin", "default", "all", "your-name", "yourname", "your_name", "someone",
    "alice", "bob", "test", "tester", "home", "app", "root", "ubuntu", "vscode", "appuser", "dev",
    "<user>", "<name>", "%username%", "$user", "${user}", "...", "…",
}

# (rule_id, severity, regex, kind) ; kind controls masking. Content rules, applied to added lines.
_SECRET_VALUE = r"[A-Za-z0-9+/=_\-]{32,}"
CONTENT_RULES = [
    ("sk_api_key", "high", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"), "secret"),
    ("ts_token", "high", re.compile(r"\bts[_-][A-Za-z0-9]{20,}"), "secret"),
    ("github_token", "high", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}"), "secret"),
    ("aws_google_slack_key", "high",
     re.compile(r"\b(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|xox[abprs]-[A-Za-z0-9\-]{10,})"), "secret"),
    ("bearer_token", "high", re.compile(r"Bearer\s+([A-Za-z0-9._~+/=\-]{20,})"), "secret"),
    ("assigned_secret", "high",
     re.compile(r"(?i)\b[\w.\-]*(?:api[_-]?key|token|secret|passw(?:or)?d|passwd)[\w.\-]*[\"']?\s*[:=]\s*[\"']?(" + _SECRET_VALUE + r")[\"']?"),
     "secret"),
    ("private_key_block", "high", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"), "secret"),
    ("personal_path_windows", "medium",
     re.compile(r"(?i)\b[A-Z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)([^\\/\s\"'<>*:|?`]+)"), "path"),
    ("personal_path_posix", "medium", re.compile(r"(?<![\w.])/(?:home|Users)/([A-Za-z0-9._\-]+)"), "path"),
    ("vault_folder_marker", "medium",
     re.compile(r"(?:\b[0-9]{2}-(?:Projetos|Pessoal|Inbox|Areas|Recursos|Arquivo)\b/?|Cérebro_AI|Cerebro_AI)"),
     "marker"),
    # `.obsidian` is a legitimate directory name that code must skip; kept as informational.
    ("obsidian_dir_reference", "low", re.compile(r"\.obsidian\b"), "marker"),
]
# The synthetic corpus deliberately mimics the vault folder layout with invented names.
SYNTHETIC_PREFIXES = (
    "data/synthetic_vault/", "benchmark/synthetic_questions.json", "benchmark/routing_tasks.json",
    "benchmark/questions.example.json", "scripts/gen_synthetic_corpus.py", "scripts/gen_routing_tasks.py",
)
SYNTHETIC_EXEMPT_RULES = {"vault_folder_marker", "obsidian_dir_reference"}
# Wikilinks only matter in data files (docs/notes legitimately use them).
WIKILINK = re.compile(r"\[\[[^\]\n]{2,80}\]\]")
DATA_EXT = {".json", ".jsonl", ".csv", ".yaml", ".yml", ".tsv"}
WIKILINK_EXEMPT_PREFIXES = ("data/synthetic_vault/", "tests/", "docs/", "frontend/")

# Path rules: (rule_id, severity, matcher(path)->bool)
def _p(path: str) -> str:
    return path.replace("\\", "/")

PATH_RULES = [
    ("env_file", "high", lambda p: bool(re.search(r"(^|/)\.env(\.|$)", p)) and not p.endswith(".example")),
    ("sqlite_db_file", "high", lambda p: bool(re.search(r"\.(db|db-shm|db-wal|db-journal|sqlite3?|sqlite-shm|sqlite-wal)$", p))),
    ("benchmark_db", "high", lambda p: os.path.basename(p).startswith("benchmark.db")),
    ("log_file", "medium", lambda p: p.startswith("logs/") or "/logs/" in p or p.endswith((".log", ".jsonl"))),
    ("vault_mirror", "high", lambda p: p.startswith("data/vault_mirror/") or p == "data/vault_state_before.json"),
    ("private_benchmark_dataset", "high", lambda p: p == "benchmark/questions.json"),
    ("reports_dir", "low", lambda p: p.startswith("reports/")),
    ("key_or_cert_file", "high", lambda p: bool(re.search(r"\.(pem|key|p12|pfx)$", p))),
    ("data_dir_nonsynthetic", "medium",
     lambda p: p.startswith("data/") and not p.startswith("data/synthetic_vault/") and not p.endswith(".gitkeep")),
]
# Known benign path hits that are not worth flagging.
_BENIGN_PATH_RE = re.compile(r"(?:^|/)(?:tests/fixtures/)")


def _mask(kind: str, value: str, full: str) -> str:
    if kind == "secret":
        v = value if value else full
        return f"{v[:4]}…(len {len(v)})"
    if kind == "path":
        user = value
        return full.replace(user, user[:2] + "***", 1)
    return full[:24]


def _is_placeholder_user(user: str) -> bool:
    u = user.lower().strip("{}<>%$")
    return u in _PLACEHOLDER_USERS or u.startswith("<") or u.startswith("$") or u.startswith("{") or "*" in u


def _looks_like_secret_value(v: str) -> bool:
    """Reduce false positives for assigned_secret: require some entropy and not a plain identifier."""
    if re.fullmatch(r"[a-z_]+", v) or re.fullmatch(r"[A-Z_]+", v):
        return False
    if len(set(v)) < 10:
        return False
    return bool(re.search(r"\d", v)) or bool(re.search(r"[A-Z]", v) and re.search(r"[a-z]", v))


class Collector:
    def __init__(self, max_locations: int):
        self.max_locations = max_locations
        self.count: dict[str, int] = defaultdict(int)
        self.sev: dict[str, str] = {}
        self.files: dict[str, set] = defaultdict(set)
        self.commits: dict[str, set] = defaultdict(set)
        self.locations: dict[str, list] = defaultdict(list)
        self._seen: dict[str, set] = defaultdict(set)

    def add(self, rule: str, sev: str, file: str, line: int | None, masked: str, commit: str | None = None):
        self.count[rule] += 1
        self.sev[rule] = sev
        self.files[rule].add(file)
        if commit:
            self.commits[rule].add(commit)
        key = (file, masked)
        if key in self._seen[rule]:
            return
        self._seen[rule].add(key)
        if len(self.locations[rule]) < self.max_locations:
            loc = {"file": file, "masked": masked}
            if line:
                loc["line"] = line
            if commit:
                loc["commit"] = commit
            self.locations[rule].append(loc)

    def summary(self) -> dict:
        out = {}
        for rule in sorted(self.count, key=lambda r: (self.sev[r] != "high", self.sev[r] != "medium", r)):
            out[rule] = {
                "severity": self.sev[rule],
                "occurrences": self.count[rule],
                "distinct_files": len(self.files[rule]),
                "distinct_commits": len(self.commits[rule]),
                "first_locations": self.locations[rule],
            }
        return out


def scan_line(c: Collector, file: str, lineno: int | None, line: str, commit: str | None):
    if len(line) > MAX_LINE:
        line = line[:MAX_LINE]
    ext = os.path.splitext(file)[1].lower()
    synthetic = file.startswith(SYNTHETIC_PREFIXES)
    for rule, sev, rx, kind in CONTENT_RULES:
        if synthetic and rule in SYNTHETIC_EXEMPT_RULES:
            continue
        for m in rx.finditer(line):
            val = m.group(1) if m.groups() else m.group(0)
            if kind == "path" and _is_placeholder_user(val):
                continue
            if rule == "assigned_secret" and not _looks_like_secret_value(val):
                continue
            c.add(rule, sev, file, lineno, _mask(kind, val, m.group(0)), commit)
            break  # one hit per rule per line is enough
    if ext in DATA_EXT and not file.startswith(WIKILINK_EXEMPT_PREFIXES):
        m = WIKILINK.search(line)
        if m:
            c.add("wikilink_in_data_file", "medium", file, lineno, m.group(0)[:6] + "…", commit)


def scan_paths(c: Collector, paths, commit_of: dict | None = None):
    for p in paths:
        p = _p(p)
        if _BENIGN_PATH_RE.search(p):
            continue
        for rule, sev, fn in PATH_RULES:
            if fn(p):
                c.add(rule, sev, p, None, p, (commit_of or {}).get(p))


def git(repo: str, *args: str) -> subprocess.Popen:
    return subprocess.Popen(["git", "-C", repo, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def git_out(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def scan_tree(repo: str, c: Collector) -> dict:
    tracked = [p for p in git_out(repo, "ls-files", "-z").split("\0") if p]
    untracked = [p for p in git_out(repo, "ls-files", "-z", "--others", "--exclude-standard").split("\0") if p]
    files = [("tracked", p) for p in tracked] + [("untracked", p) for p in untracked]
    scan_paths(c, [p for _, p in files])
    scanned = 0
    for _, p in files:
        full = os.path.join(repo, p)
        if p == "scripts/scan_publication_safety.py":
            continue  # this file contains the rule patterns themselves
        try:
            if os.path.getsize(full) > MAX_FILE_BYTES:
                continue
            with open(full, "rb") as f:
                raw = f.read()
        except OSError:
            continue
        if b"\0" in raw[:4096]:
            continue
        scanned += 1
        for i, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            scan_line(c, _p(p), i, line, None)
    return {"tracked": len(tracked), "untracked_not_ignored": len(untracked), "text_files_scanned": scanned}


def scan_history(repo: str, c: Collector) -> dict:
    # 1) every path ever present, with the first commit that touched it
    first_commit: dict[str, str] = {}
    commit = None
    n_commits = 0
    proc = git(repo, "log", "--all", "--name-only", "--format=%x01%h")
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if line.startswith("\x01"):
            commit = line[1:]
            n_commits += 1
        elif line:
            first_commit[_p(line)] = commit  # log is newest-first, so last write == oldest commit
    proc.wait()
    scan_paths(c, list(first_commit), first_commit)
    # 2) added content lines, streamed
    proc = git(repo, "log", "--all", "-p", "-U0", "--no-color", "--no-renames", "--format=%x01%h")
    commit = None
    cur_file = None
    skip_file = False
    lineno = None
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.startswith("\x01"):
            commit = line[1:]
            cur_file = None
            continue
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/.* b/(.*)$", line)
            cur_file = _p(m.group(1)) if m else None
            skip_file = cur_file == "scripts/scan_publication_safety.py"
            lineno = None
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else None
            continue
        if cur_file and not skip_file and line.startswith("+") and not line.startswith("+++"):
            scan_line(c, cur_file, lineno, line[1:], commit)
            if lineno is not None:
                lineno += 1
    proc.wait()
    # 3) author/committer e-mails are published with the history (metadata, owner's call)
    emails: dict[str, int] = defaultdict(int)
    for e in git_out(repo, "log", "--all", "--format=%ae%n%ce").splitlines():
        if e and not e.endswith("@users.noreply.github.com"):
            emails[e] += 1
    for e, n in emails.items():
        user, _, dom = e.partition("@")
        for _ in range(n):
            c.add("commit_email_metadata", "medium", "(git author/committer metadata)", None, f"{user[:3]}***@{dom}")
    return {"commits": n_commits, "distinct_paths_ever": len(first_commit)}


def large_files(repo: str) -> dict:
    tracked = []
    for p in git_out(repo, "ls-files", "-z").split("\0"):
        if not p:
            continue
        try:
            s = os.path.getsize(os.path.join(repo, p))
        except OSError:
            continue
        if s > LARGE_BYTES:
            tracked.append({"path": _p(p), "bytes": s})
    tracked.sort(key=lambda d: -d["bytes"])
    # blobs in history (any commit) > 1 MB
    hist = []
    p1 = git(repo, "rev-list", "--objects", "--all")
    p2 = subprocess.Popen(["git", "-C", repo, "cat-file", "--batch-check=%(objecttype) %(objectsize) %(rest)"],
                          stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    for raw in p2.stdout:
        parts = raw.decode("utf-8", errors="replace").rstrip("\n").split(" ", 2)
        if len(parts) == 3 and parts[0] == "blob" and parts[1].isdigit() and int(parts[1]) > LARGE_BYTES:
            hist.append({"path": _p(parts[2]), "bytes": int(parts[1])})
    p2.wait()
    hist.sort(key=lambda d: -d["bytes"])
    return {"tracked_over_1MB": tracked, "history_blobs_over_1MB": hist[:50]}


def tracked_but_ignored(repo: str) -> list[str]:
    return [_p(p) for p in git_out(repo, "ls-files", "-ci", "--exclude-standard", "-z").split("\0") if p]


def render_md(rep: dict) -> str:
    L = ["# Publication safety report", "",
         f"- repo: `{rep['repo']}`",
         f"- tree: {rep['tree_stats']}",
         f"- history: {rep.get('history_stats', 'not scanned')}", ""]
    for scope in ("tree", "history"):
        if scope not in rep:
            continue
        L += [f"## {scope}", "", "| rule | severity | occurrences | files | commits | first locations (masked) |", "|---|---|---|---|---|---|"]
        data = rep[scope]
        if not data:
            L.append("| (none) | | 0 | | | |")
        for rule, d in data.items():
            locs = "<br>".join(
                f"`{l['file']}" + (f":{l['line']}" if 'line' in l else "") + f"` {l['masked']}"
                + (f" @{l['commit']}" if l.get("commit") else "") for l in d["first_locations"])
            L.append(f"| {rule} | {d['severity']} | {d['occurrences']} | {d['distinct_files']} | {d['distinct_commits']} | {locs} |")
        L.append("")
    L += ["## Large files", "",
          f"- tracked > 1 MB: {rep['large']['tracked_over_1MB'] or 'none'}",
          f"- blobs > 1 MB anywhere in history: {len(rep['large']['history_blobs_over_1MB'])}"]
    for b in rep["large"]["history_blobs_over_1MB"][:10]:
        L.append(f"  - `{b['path']}` {b['bytes']:,} bytes")
    L += ["", "## Tracked but ignored by .gitignore (`git ls-files -ci --exclude-standard`)", ""]
    L += [f"- `{p}`" for p in rep["tracked_but_ignored"]] or ["- none"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out-dir", default="reports")
    ap.add_argument("--max-locations", type=int, default=10)
    ap.add_argument("--no-history", action="store_true")
    ap.add_argument("--fail-on-findings", action="store_true")
    a = ap.parse_args(argv)
    repo = os.path.abspath(a.repo)

    rep: dict = {"repo": repo}
    ct = Collector(a.max_locations)
    rep["tree_stats"] = scan_tree(repo, ct)
    rep["tree"] = ct.summary()
    if not a.no_history:
        ch = Collector(a.max_locations)
        rep["history_stats"] = scan_history(repo, ch)
        rep["history"] = ch.summary()
    rep["large"] = large_files(repo)
    rep["tracked_but_ignored"] = tracked_but_ignored(repo)

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "publication_safety_report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    md = render_md(rep)
    (out / "publication_safety_report.md").write_text(md, encoding="utf-8")
    sys.stdout.buffer.write(md.encode("utf-8", errors="replace"))
    high = sum(d["occurrences"] for scope in ("tree", "history") for d in rep.get(scope, {}).values()
               if d["severity"] == "high")
    print(f"\nhigh-severity occurrences: {high}")
    return 1 if (a.fail_on_findings and high) else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""ANA-172: compare config/models.yaml ids against model lists the user already has. NO inference, NO keys.

Sources of model lists (per provider):
  --offline FILE.json     {"ollama": ["qwen3.5:9b", ...], "anthropic": [...]}  (default; fully offline)
  --base-url PROV=URL     list_models of an OpenAI-compatible /models (or Ollama /api/tags). Loopback URLs
                          (127.0.0.1/localhost: local Ollama or a fake test server) are always allowed; any
                          other host needs ANAMNESIA_ALLOW_NETWORK_TEST=1. No credential is ever sent.
Only list_models is ever called. A provider without a list stays `unknown_no_list` (its flag is untouched).

Rules applied by --write (in place; comments and line endings preserved):
  * id in list AND context_window set -> verified: true
  * id in list but context_window null -> verified: false (ANA-179: the window must be confirmed too)
  * list present, id absent            -> verified: false
Prices are never written by --write. ANA-172/179: `--fill-openrouter URL` (e.g. https://openrouter.ai/api/v1/models,
public, NO credential) additionally copies `context_length` and `pricing` of each `provider: openrouter` entry found
in that list into the registry (price per 1M tokens, source_url + checked_at = today), then `verified` follows the
rules above. Other providers are never touched: the OpenRouter list says nothing about their own price pages.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.routing.registry import DEFAULT_PATH, coverage_report, load_registry  # noqa: E402

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def network_allowed() -> bool:
    return os.getenv("ANAMNESIA_ALLOW_NETWORK_TEST", "").strip() == "1"


def id_in_list(provider: str, model: str, ids) -> bool:
    ids = list(ids)
    if model in ids:
        return True
    if provider in ("ollama", "vllm") and ":" not in model:      # `x` is served as `x:latest`
        return any(i.split(":")[0] == model for i in ids)
    return False


def fetch_list(provider: str, url: str, timeout: float = 3.0) -> list[str]:
    """list_models only. PermissionError for a non-loopback host unless the network flag is set."""
    host = (urlparse(url).hostname or "").lower()
    if host not in LOOPBACK and not network_allowed():
        raise PermissionError(f"{host}: non-loopback needs ANAMNESIA_ALLOW_NETWORK_TEST=1")
    import httpx
    base = url.rstrip("/")
    if provider == "ollama":
        r = httpx.get(f"{base}/api/tags", timeout=timeout)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    r = httpx.get(f"{base}/models", timeout=timeout)             # no Authorization header, ever
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def fetch_openrouter_models(url: str, timeout: float = 20.0) -> list[dict]:
    """Full model objects (id, context_length, pricing) from the PUBLIC OpenRouter /models. No credential sent."""
    host = (urlparse(url).hostname or "").lower()
    if host not in LOOPBACK and not network_allowed():
        raise PermissionError(f"{host}: non-loopback needs ANAMNESIA_ALLOW_NETWORK_TEST=1")
    import httpx
    r = httpx.get(url.rstrip("/"), timeout=timeout)
    r.raise_for_status()
    return list(r.json().get("data", []))


def _per_mtok(v) -> float | None:
    try:
        return round(float(v) * 1_000_000, 6)
    except (TypeError, ValueError):
        return None


def fill_openrouter(text: str, registry, models: list[dict], source_url: str, checked_at: str) -> tuple[str, list[dict]]:
    """Rewrite `context_window:` and `price:` of openrouter entries from `models`. Only entries whose id is in the
    list, whose context_length is a positive int and whose prompt/completion price are numbers are filled.
    Returns (new_text, report). Everything else (comments, other entries, line endings) is preserved."""
    by = {m.get("id"): m for m in models if isinstance(m, dict)}
    wanted = {e.id: by[e.model] for e in registry.models if e.provider == "openrouter" and e.model in by}
    lines = text.splitlines(keepends=True)
    out, report, cur, i = [], [], None, 0
    while i < len(lines):
        ln = lines[i]
        eol = "\r\n" if ln.endswith("\r\n") else ("\n" if ln.endswith("\n") else "")
        m = re.match(r"^\s*-\s+id:\s*(\S+)", ln)
        if m:
            cur = m.group(1)
        src = wanted.get(cur)
        if src is not None:
            mc = re.match(r"^(\s+)context_window:\s*(null)\s*(#.*)?$", ln.rstrip("\r\n"))
            mp = re.match(r"^(\s+)price:\s*(null)\s*(#.*)?$", ln.rstrip("\r\n"))
            cl = src.get("context_length")
            pr = src.get("pricing") or {}
            pin, pout = _per_mtok(pr.get("prompt")), _per_mtok(pr.get("completion"))
            if mc and isinstance(cl, int) and not isinstance(cl, bool) and cl > 0:
                out.append(f"{mc.group(1)}context_window: {cl}   # openrouter /models context_length ({checked_at}){eol}")
                report.append({"id": cur, "field": "context_window", "value": cl})
                i += 1
                continue
            if mp is not None and pin is not None and pout is not None:
                ind = mp.group(1)
                out.append(f"{ind}price:{eol}")
                out.append(f"{ind}  input: {pin}{eol}{ind}  output: {pout}{eol}")
                out.append(f"{ind}  source_url: {source_url}{eol}{ind}  checked_at: {checked_at}{eol}")
                report.append({"id": cur, "field": "price", "input_per_mtok": pin, "output_per_mtok": pout})
                i += 1
                while i < len(lines) and re.match(rf"^{ind}\s+\S", lines[i]):     # drop an old multi-line price block
                    i += 1
                continue
        out.append(ln)
        i += 1
    return "".join(out), report


def verify(registry, lists: dict) -> dict:
    """Pure comparison: no I/O."""
    rows = []
    for m in registry.models:
        row = {"id": m.id, "provider": m.provider, "set_verified": None}
        ids = lists.get(m.provider)
        if m.planned:
            row["status"] = "planned"
        elif ids is None:
            row["status"] = "unknown_no_list"
        elif id_in_list(m.provider, m.model, ids):
            ok = m.context_window is not None
            row.update(status="verified" if ok else "id_found_window_missing", set_verified=ok)
        else:
            row.update(status="id_not_in_list", set_verified=False)
        rows.append(row)
    return {"models": rows, "coverage_before": coverage_report(registry)}


def apply_verified(text: str, updates: dict) -> str:
    """Rewrite only the `verified:` line of listed entries; every other byte is kept."""
    lines = text.splitlines(keepends=True)
    cur = None
    for i, ln in enumerate(lines):
        m = re.match(r"^\s*-\s+id:\s*(\S+)", ln)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^(\s+)verified:\s*(true|false)(\s*#.*?)?(\r?\n)?$", ln)
        if m and cur in updates:
            want = "true" if updates[cur] else "false"
            if m.group(2) != want:
                lines[i] = f"{m.group(1)}verified: {want}{m.group(4) or ''}"
    return "".join(lines)


def summarize(result: dict, registry) -> dict:
    rows = result["models"]
    real = [(m, r) for m, r in zip(registry.models, rows) if r["status"] != "planned"]
    n = len(real) or 1
    after = sum(1 for m, r in real if (r["set_verified"] if r["set_verified"] is not None else m.verified))
    cov = result["coverage_before"]
    return {
        "considered": len(real), "planned_skipped": len(rows) - len(real),
        "statuses": {s: sum(1 for r in rows if r["status"] == s) for s in sorted({r["status"] for r in rows})},
        "verified_pct_before": cov["verified_pct"], "verified_pct_after": round(100.0 * after / n, 1),
        "with_price": cov["with_price"], "with_price_pct": cov["with_price_pct"],
        "context_window_null_count": cov["context_window_null_count"],
        "context_window_null": cov["context_window_null"],
    }


def _tmp_registry(text: str) -> Path:
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8", newline="")
    f.write(text)
    f.close()
    return Path(f.name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ANA-172 registry verification (list_models only)")
    ap.add_argument("--registry", default=str(DEFAULT_PATH))
    ap.add_argument("--offline", help="JSON file {provider: [model ids]}")
    ap.add_argument("--base-url", action="append", default=[], metavar="PROV=URL")
    ap.add_argument("--fill-openrouter", metavar="URL", help="ANA-172/179: copy context_length + pricing of openrouter "
                    "entries from the public OpenRouter /models (needs ANAMNESIA_ALLOW_NETWORK_TEST=1; with --write)")
    ap.add_argument("--checked-at", default=None, help="YYYY-MM-DD for filled prices (default: today)")
    ap.add_argument("--write", action="store_true", help="persist `verified` into the registry file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    reg_path = Path(a.registry)
    registry = load_registry(reg_path)
    lists: dict = {}
    errors: dict = {}
    if a.offline:
        for prov, ids in json.loads(Path(a.offline).read_text(encoding="utf-8")).items():
            lists[prov] = [i["id"] if isinstance(i, dict) else i for i in ids]
    for spec in a.base_url:
        prov, _, url = spec.partition("=")
        try:
            lists[prov] = fetch_list(prov, url)
        except Exception as exc:  # noqa: BLE001 — a dead server just means "unknown"
            errors[prov] = f"{type(exc).__name__}: {str(exc)[:120]}"
    filled: list[dict] = []
    if a.fill_openrouter:
        import datetime
        try:
            models = fetch_openrouter_models(a.fill_openrouter)
            lists["openrouter"] = [m.get("id") for m in models]
            when = a.checked_at or datetime.date.today().isoformat()
            old = reg_path.read_bytes().decode("utf-8")
            new, filled = fill_openrouter(old, registry, models, a.fill_openrouter.rstrip("/"), when)
            if a.write and new != old:
                reg_path.write_bytes(new.encode("utf-8"))
                try:
                    registry = load_registry(reg_path)
                except Exception:
                    reg_path.write_bytes(old.encode("utf-8"))
                    raise
            elif new != old:
                import tempfile
                registry = load_registry(_tmp_registry(new))      # dry run: evaluate on the would-be text
        except Exception as exc:  # noqa: BLE001
            errors["openrouter"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    result = verify(registry, lists)
    summ = summarize(result, registry)
    summ["filled"] = filled
    summ["lists_used"] = {p: len(v) for p, v in lists.items()}
    summ["list_errors"] = errors
    if a.write:
        updates = {r["id"]: r["set_verified"] for r in result["models"] if r["set_verified"] is not None}
        old = reg_path.read_bytes().decode("utf-8")
        new = apply_verified(old, updates)
        if new != old:
            reg_path.write_bytes(new.encode("utf-8"))
        try:
            load_registry(reg_path)                          # must still validate after the edit
        except Exception:
            reg_path.write_bytes(old.encode("utf-8"))
            raise
        summ["written"] = new != old
    if a.json:
        print(json.dumps({"summary": summ, "models": result["models"]}, ensure_ascii=False, indent=1))
    else:
        s = summ
        print(f"considered={s['considered']} planned_skipped={s['planned_skipped']} statuses={s['statuses']}")
        print(f"verified: {s['verified_pct_before']}% -> {s['verified_pct_after']}% | with price: "
              f"{s['with_price_pct']}% | context_window null: {s['context_window_null_count']} "
              f"{s['context_window_null']}")
        if s["list_errors"]:
            print("list errors:", s["list_errors"])
        if not lists:
            print("no model lists given (use --offline FILE.json or --base-url): nothing could be verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

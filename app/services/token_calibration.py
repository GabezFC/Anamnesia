"""ANA-183: provider-reported tokens (usage) vs our estimator, error % per model / language. PURE and offline.

DEFAULT BEHAVIOUR IS NOT CHANGED: `app.services.token_estimate.estimate_tokens` keeps its heuristic. This module
only MEASURES the error and can PROPOSE a factor file for ANAMNESIA_TOKEN_CALIBRATION (read by token_estimate only
if the variable exists). A proposal needs n >= MIN_N (100) pairs per language, otherwise the verdict is HOLD and no
factor is produced. Simulated (stub) pairs never count: they carry no provider usage.

error_pct = (estimated - provider) / provider * 100   (positive = we over-estimate)
"""
from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

MIN_N = 100
ENV_CALIBRATION = "ANAMNESIA_TOKEN_CALIBRATION"


def pairs_from_records(records: Iterable[dict], model_key: str = "final_model") -> list[dict]:
    """(model, lang, estimated, provider) from benchmark records that have both figures and are not simulated."""
    out = []
    for r in records:
        est, prov = r.get("estimated_input_tokens"), r.get("provider_input_tokens")
        if r.get("simulated") or est is None or prov is None or prov <= 0:
            continue
        out.append({"model": r.get(model_key) or r.get("model") or "unknown", "lang": r.get("prompt_lang") or "unknown",
                    "estimated": int(est), "provider": int(prov)})
    return out


def error_pct(estimated: int, provider: int) -> float | None:
    return None if provider is None or provider <= 0 or estimated is None else (estimated - provider) / provider * 100.0


def calibration_error(pairs: Sequence[dict]) -> dict:
    """{"by_model_lang": {"model|lang": {n, mean_error_pct, mean_abs_error_pct, median_ratio, status}}, "overall": {...}}.
    status: 'ok' (n >= MIN_N) | 'HOLD_insufficient_n'."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for p in pairs:
        if p.get("provider") and p["provider"] > 0 and p.get("estimated") is not None:
            groups[(p["model"], p["lang"])].append(p)

    def stats(ps: list[dict]) -> dict:
        errs = [error_pct(p["estimated"], p["provider"]) for p in ps]
        ratios = [p["provider"] / p["estimated"] for p in ps if p["estimated"] > 0]
        n = len(ps)
        return {"n": n, "mean_error_pct": round(statistics.fmean(errs), 3), "mean_abs_error_pct": round(statistics.fmean(abs(e) for e in errs), 3),
                "median_ratio_provider_over_estimate": round(statistics.median(ratios), 4) if ratios else None,
                "status": "ok" if n >= MIN_N else "HOLD_insufficient_n", "origin": "measured"}

    out = {"by_model_lang": {f"{m}|{lg}": stats(ps) for (m, lg), ps in sorted(groups.items())}, "min_n": MIN_N}
    allp = [p for ps in groups.values() for p in ps]
    out["overall"] = stats(allp) if allp else {"n": 0, "status": "no_data", "origin": "unavailable"}
    return out


def propose_factors(pairs: Sequence[dict]) -> dict:
    """Candidate file content for ANAMNESIA_TOKEN_CALIBRATION, or a HOLD. Factors are RELATIVE TO THE RAW heuristic
    (see token_estimate), so the proposal is provider/estimate ratio median per language -- only when n >= MIN_N for
    that language. Returns {"status": "HOLD"|"READY", "factors": {...}, "reason": ...}. Writes nothing."""
    by_lang: dict[str, list[float]] = defaultdict(list)
    for p in pairs:
        if p.get("estimated") and p["estimated"] > 0 and p.get("provider") and p["provider"] > 0:
            by_lang[p["lang"] if p["lang"] in ("pt", "other") else "other"].append(p["provider"] / p["estimated"])
    factors, held = {}, {}
    for lg, ratios in by_lang.items():
        if len(ratios) >= MIN_N:
            factors[lg] = round(statistics.median(ratios), 4)
        else:
            held[lg] = len(ratios)
    if not factors:
        return {"status": "HOLD", "factors": {}, "reason": f"n < {MIN_N} per language: {held or 'no pairs'}; default estimator kept"}
    return {"status": "READY", "factors": factors, "held": held,
            "reason": "median(provider/estimate) per language; ratios are against the CURRENT estimate, so re-derive vs the raw "
                      "heuristic before use. Not applied automatically."}


def active_calibration() -> dict:
    """Is the optional env file in effect? Reads the variable only if it exists; never creates/changes anything."""
    p = os.environ.get(ENV_CALIBRATION, "").strip()
    if not p:
        return {"active": False, "path": None}
    return {"active": Path(p).is_file(), "path": p}


def render_report(pairs: Sequence[dict]) -> str:
    err = calibration_error(pairs)
    prop = propose_factors(pairs)
    lines = ["# Erro do estimador de tokens vs. contagem do provedor (ANA-183)", "",
             f"Pares válidos (não simulados, com usage): {err['overall'].get('n', 0)}. Mínimo para recalibrar: n>={MIN_N} por idioma.", "",
             "| modelo|idioma | n | erro médio % | erro abs. médio % | status |", "|---|---|---|---|---|"]
    for k, v in err["by_model_lang"].items():
        lines.append(f"| {k} | {v['n']} | {v['mean_error_pct']} | {v['mean_abs_error_pct']} | {v['status']} |")
    if not err["by_model_lang"]:
        lines.append("| — | 0 | indisponível | indisponível | no_data |")
    lines += ["", f"Proposta: **{prop['status']}** — {prop['reason']}", "",
              "O default de estimativa NÃO foi alterado."]
    return "\n".join(lines) + "\n"


def write_proposal(path: str | os.PathLike, pairs: Sequence[dict]) -> dict:
    """Write the candidate JSON ONLY if READY (n>=100/lang). Never points the env var at it."""
    prop = propose_factors(pairs)
    if prop["status"] != "READY":
        return prop
    Path(path).write_text(json.dumps({**prop["factors"], "source": "provider usage vs estimate", "n_min": MIN_N}, indent=2),
                          encoding="utf-8")
    return prop

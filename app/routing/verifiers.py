"""R4: no-LLM verifiers for routing success (pure functions, no network).

Levels: NONE (no verification) < LIGHT (no-LLM verifiers) < FULL (LIGHT + LLM-judge hook, not implemented).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence


class VerifyLevel(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    FULL = "FULL"


@dataclass(frozen=True)
class VerifyResult:
    passed: bool | None          # None = not run
    level: VerifyLevel
    failure_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _ok(level=VerifyLevel.LIGHT, **d) -> VerifyResult:
    return VerifyResult(True, level, None, d)


def _fail(code: str, level=VerifyLevel.LIGHT, **d) -> VerifyResult:
    return VerifyResult(False, level, code, d)


# ---------------------------------------------------------------- normalization
def normalize(text: str) -> str:
    """Lowercase, strip accents, unify decimal comma and '157 ms' -> '157ms', collapse punctuation."""
    t = unicodedata.normalize("NFKD", str(text))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = re.sub(r"(?<=\d),(?=\d)", ".", t)
    t = re.sub(r"(?<=\d)\s+(?=[a-z%])", "", t)
    t = re.sub(r"[^a-z0-9.%:/_\-]+", " ", t)
    t = re.sub(r"(?<![a-z0-9])\.+|\.+(?![a-z0-9])", " ", t)  # drop sentence dots, keep 7.111
    return re.sub(r"\s+", " ", t).strip()


_STOP = frozenset(
    "de da do das dos a o as os e em um uma para por com que se na no nas nos ao aos ou foi ser "
    "the of and to in is it for on as at by an be this that".split())


def _tokens(text: str) -> set[str]:
    return {w for w in normalize(text).split(" ") if len(w) >= 3 and w not in _STOP}


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p and len(p.strip()) > 1]


# ---------------------------------------------------------------- grounding
def verify_grounding(answer: str, snippets: Sequence[str], threshold: float = 0.6) -> VerifyResult:
    """Every sentence of `answer` must have >= threshold of its content tokens in the snippets."""
    sents = split_sentences(answer or "")
    if not sents:
        return _fail("empty_answer")
    if not snippets:
        return _fail("no_snippets")
    pool: set[str] = set()
    for s in snippets:
        pool |= _tokens(s)
    unsupported = []
    for s in sents:
        toks = _tokens(s)
        if not toks:
            continue
        cov = len(toks & pool) / len(toks)
        if cov < threshold:
            unsupported.append({"sentence": s, "coverage": round(cov, 3)})
    if unsupported:
        return _fail("ungrounded_sentence", threshold=threshold, unsupported=unsupported)
    return _ok(threshold=threshold, sentences=len(sents))


# ---------------------------------------------------------------- citation
def verify_citation(cited_ids: Iterable[str], retrieved_ids: Iterable[str],
                    require_at_least_one: bool = True) -> VerifyResult:
    cited = list(dict.fromkeys(cited_ids))
    retrieved = set(retrieved_ids)
    if require_at_least_one and not cited:
        return _fail("no_citation")
    missing = [c for c in cited if c not in retrieved]
    if missing:
        return _fail("citation_not_retrieved", missing=missing)
    return _ok(cited=cited)


# ---------------------------------------------------------------- fact match
def verify_fact_match(answer: str, expected_facts: Sequence[str], mode: str = "all") -> VerifyResult:
    """Expected facts (ground truth) must appear in answer after normalization. mode: all|any."""
    if not expected_facts:
        return _fail("no_expected_facts")
    na = normalize(answer or "")
    found = [f for f in expected_facts if normalize(f) and normalize(f) in na]
    missing = [f for f in expected_facts if f not in found]
    ok = (len(found) == len(expected_facts)) if mode == "all" else bool(found)
    if ok:
        return _ok(found=found)
    return _fail("fact_missing", found=found, missing=missing)


_ABSTAIN = ("nao existe", "nao ha ", "nao encontr", "nao tenho", "sem informacao", "nao consta",
            "not found", "no information", "cannot find", "i don't know", "nao sei")


def verify_abstention(answer: str) -> VerifyResult:
    """For unanswerable tasks: the answer must abstain (success = refusing to invent)."""
    na = normalize(answer or "") + " "
    if any(m in na for m in _ABSTAIN):
        return _ok()
    return _fail("hallucinated_answer")


# ---------------------------------------------------------------- JSON schema subset
_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None,
}


def _check(value: Any, schema: dict, path: str, errors: list[str]) -> None:
    t = schema.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_TYPES.get(x, lambda v: False)(value) for x in ts):
            errors.append(f"{path}: expected type {t}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: not in enum")
    if isinstance(value, dict):
        for r in schema.get("required", []):
            if r not in value:
                errors.append(f"{path}.{r}: required")
        for k, sub in schema.get("properties", {}).items():
            if k in value:
                _check(value[k], sub, f"{path}.{k}", errors)
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(value):
            _check(v, schema["items"], f"{path}[{i}]", errors)


def verify_json_schema(output: Any, schema: dict) -> VerifyResult:
    """Subset: type, required, enum, properties, items. `output` may be a JSON string."""
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (ValueError, TypeError):
            return _fail("invalid_json")
    errors: list[str] = []
    _check(output, schema, "$", errors)
    if errors:
        return _fail("schema_violation", errors=errors)
    return _ok()


# ---------------------------------------------------------------- tests-pass wrapper
def verify_tests_pass(command: Sequence[str] | None, sandbox_dir: str | None, timeout_s: float = 60.0,
                      enabled: bool = False) -> VerifyResult:
    """Run `command` (argv list, no shell) in a temp COPY of sandbox_dir. Only runs if enabled=True.

    Disabled -> passed=None, failure_code='not_run'. Exit code 0 == pass.
    """
    if not enabled:
        return VerifyResult(None, VerifyLevel.LIGHT, "not_run", {"reason": "disabled"})
    if not command or not sandbox_dir or not os.path.isdir(sandbox_dir):
        return _fail("bad_config")
    tmp = tempfile.mkdtemp(prefix="routing_sbx_")
    work = os.path.join(tmp, "work")
    try:
        shutil.copytree(sandbox_dir, work)
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")}
        try:
            p = subprocess.run(list(command), cwd=work, env=env, capture_output=True, text=True,
                               timeout=timeout_s, shell=False)
        except subprocess.TimeoutExpired:
            return _fail("timeout", timeout_s=timeout_s)
        except OSError as e:
            return _fail("exec_error", error=str(e))
        tail = (p.stdout or "")[-500:]
        if p.returncode == 0:
            return _ok(returncode=0, tail=tail)
        return _fail("tests_failed", returncode=p.returncode, tail=tail)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- LLM judge hook + level dispatch
def llm_judge_hook(*_a, **_k) -> VerifyResult:
    """Placeholder for FULL level (LLM judge). Not implemented."""
    return VerifyResult(None, VerifyLevel.FULL, "not_run", {"reason": "llm_judge_not_implemented"})


def run_level(level: VerifyLevel | str, light_results: Sequence[VerifyResult]) -> VerifyResult:
    """NONE -> not run; LIGHT -> all light results must pass; FULL -> LIGHT + judge hook (not_run, not blocking)."""
    level = VerifyLevel(level)
    if level == VerifyLevel.NONE:
        return VerifyResult(None, level, "not_run", {})
    bad = [r for r in light_results if r.passed is False]
    judge = llm_judge_hook() if level == VerifyLevel.FULL else None
    details = {"checks": len(light_results), "judge": judge.failure_code if judge else None}
    if bad:
        return VerifyResult(False, level, bad[0].failure_code, details)
    if not light_results or all(r.passed is None for r in light_results):
        return VerifyResult(None, level, "not_run", details)
    return VerifyResult(True, level, None, details)

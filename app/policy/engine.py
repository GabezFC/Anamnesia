"""ANA-176: minimal, honest policy engine.

Declarative rules (config/policy.yaml, mini-YAML subset parsed by app.routing.registry._parse_yaml) over five
actions: read | write | escalate | pay | exec. Default-deny for write, exec, pay and escalate; read is allowed.

Mode (env ``ANAMNESIA_POLICY``; default ``off`` = the engine does nothing and writes nothing):
  off      check() returns an allowed Decision, no audit line.
  audit    evaluate + append an audit line, never raise (dry run of the policy).
  enforce  evaluate + audit; ``require()`` raises PolicyDenied on a deny.   ("1"/"on"/"true" = enforce)

Audit: append-only jsonl with a hash chain (``prev``/``hash``; see ``verify_chain``). It records actor, action,
target (truncated), decision, rule id, run/step ids -- never payloads, prompts or argv. Path: env
``ANAMNESIA_POLICY_AUDIT`` or ``<logs>/policy_audit.jsonl``. This chain is NEW and separate from
``exec_audit.jsonl`` (ANA-024); ANA-067 (unified audit trail) is only PARTIAL: see Cérebro IA (Anamnesia/Guias-de-usuario-2026-10-24/POLICY_ENFORCEMENT.md).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ACTIONS = ("read", "write", "escalate", "pay", "exec")
MODES = ("off", "audit", "enforce")
DEFAULT_EFFECTS = {"read": "allow", "write": "deny", "escalate": "deny", "pay": "deny", "exec": "deny"}
DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "policy.yaml"
TARGET_MAX = 200
CTX_KEYS = ("run_id", "step", "source")

_audit_lock = threading.Lock()
_tails: dict[str, str] = {}


class PolicyError(ValueError):
    pass


class PolicyDenied(PermissionError):
    def __init__(self, decision: "Decision"):
        super().__init__(f"policy denied {decision.action} {decision.target!r} for {decision.actor}"
                         f" (rule {decision.rule})")
        self.decision = decision


@dataclass(frozen=True)
class Rule:
    id: str
    effect: str                # allow | deny
    action: str
    actor: str = "*"
    target: str = "*"
    within_cwd: bool = False   # target must be a path inside ctx['cwd']


@dataclass(frozen=True)
class Decision:
    allowed: bool
    action: str
    target: str
    actor: str
    rule: str
    mode: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "action": self.action, "target": self.target, "actor": self.actor,
                "rule": self.rule, "mode": self.mode, "reason": self.reason}


@dataclass
class Policy:
    defaults: dict = field(default_factory=lambda: dict(DEFAULT_EFFECTS))
    rules: tuple = ()
    source: str = "builtin"


def mode() -> str:
    raw = os.environ.get("ANAMNESIA_POLICY", "").strip().lower()
    if raw in ("", "0", "off", "false", "no"):
        return "off"
    if raw == "audit":
        return "audit"
    return "enforce" if raw in ("1", "on", "true", "yes", "enforce") else "off"


def parse_policy(doc, source: str = "inline") -> Policy:
    if not isinstance(doc, dict):
        raise PolicyError("policy must be a mapping")
    defaults = dict(DEFAULT_EFFECTS)
    for k, v in (doc.get("defaults") or {}).items():
        if k not in ACTIONS or v not in ("allow", "deny"):
            raise PolicyError(f"bad default {k!r}: {v!r}")
        defaults[k] = v
    rules, seen = [], set()
    for i, r in enumerate(doc.get("rules") or []):
        if not isinstance(r, dict):
            raise PolicyError(f"rules[{i}] must be a mapping")
        rid = str(r.get("id") or f"rule-{i + 1}")
        if rid in seen:
            raise PolicyError(f"duplicate rule id {rid!r}")
        seen.add(rid)
        if r.get("action") not in ACTIONS:
            raise PolicyError(f"{rid}: unknown action {r.get('action')!r}")
        if r.get("effect") not in ("allow", "deny"):
            raise PolicyError(f"{rid}: effect must be allow|deny")
        rules.append(Rule(rid, r["effect"], r["action"], str(r.get("actor", "*")), str(r.get("target", "*")),
                          bool(r.get("within_cwd", False))))
    return Policy(defaults, tuple(rules), source)


def load_policy(path=None) -> Policy:
    p = Path(path or os.environ.get("ANAMNESIA_POLICY_FILE") or DEFAULT_POLICY_PATH)
    if not p.is_file():
        return Policy(source="builtin-defaults")   # file missing -> defaults only (still default-deny)
    from app.routing.registry import RegistryError, _parse_yaml
    try:
        return parse_policy(_parse_yaml(p.read_text(encoding="utf-8")), str(p))
    except RegistryError as e:
        raise PolicyError(f"{p}: {e}") from e


def _norm(t) -> str:
    return str(t).replace("\\", "/")


def _inside(target: str, cwd: str) -> bool:
    base = os.path.normcase(os.path.realpath(cwd))
    p = Path(target)
    p = p if p.is_absolute() else Path(base) / p
    real = os.path.normcase(os.path.realpath(p))
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def _matches(r: Rule, action: str, target: str, actor: str, cwd) -> bool:
    if r.action != action or not fnmatch.fnmatchcase(actor, r.actor) or not fnmatch.fnmatchcase(target, r.target):
        return False
    return not r.within_cwd or (cwd is not None and _inside(target, str(cwd)))


def evaluate(policy: Policy, action: str, target, ctx: dict | None = None) -> tuple[bool, str]:
    """Pure evaluation: (allowed, rule_id). A matching deny beats any allow; then allow; then the default."""
    ctx = ctx or {}
    if action not in ACTIONS:
        return False, "unknown_action"
    t, actor, cwd = _norm(target), str(ctx.get("actor") or "unknown"), ctx.get("cwd")
    hits = [r for r in policy.rules if _matches(r, action, t, actor, cwd)]
    for r in hits:
        if r.effect == "deny":
            return False, r.id
    for r in hits:
        return True, r.id
    return policy.defaults.get(action, "deny") == "allow", f"default:{action}"


# ---------------------------------------------------------------- audit (append-only, hash chained)
def audit_path() -> Path:
    env = os.environ.get("ANAMNESIA_POLICY_AUDIT")
    if env:
        return Path(env)
    from app.services.metrics import LOG_DIR
    return Path(LOG_DIR) / "policy_audit.jsonl"


def _hash(prev: str, rec: dict) -> str:
    return hashlib.sha256((prev + json.dumps(rec, sort_keys=True, ensure_ascii=False, default=str)).encode()).hexdigest()


def audit(event: str, rec: dict) -> dict:
    """Append one chained line. Never raises into the caller's path; returns the written record ({} on I/O error)."""
    path = audit_path()
    key = str(path)
    body = {"ts": time.time(), "event": event, **rec}
    try:
        with _audit_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            prev = _tails.get(key)
            if prev is None or not path.exists():
                prev = "0" * 64
                if path.exists():
                    for line in path.read_text(encoding="utf-8").splitlines()[-1:]:
                        prev = json.loads(line).get("hash", prev)
            body["prev"] = prev
            body["hash"] = _hash(prev, {k: v for k, v in body.items() if k != "hash"})
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(body, ensure_ascii=False, default=str) + "\n")
            _tails[key] = body["hash"]
        return body
    except Exception:  # noqa: BLE001 - auditing must not crash the caller (deny still applies)
        return {}


def read_audit(path=None) -> list:
    p = Path(path) if path else audit_path()
    if not p.is_file():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def verify_chain(path=None) -> tuple[bool, int]:
    """(ok, n_lines). ok=False if any line was edited, removed or reordered."""
    prev = "0" * 64
    rows = read_audit(path)
    for row in rows:
        h = row.pop("hash", None)
        if row.get("prev") != prev or _hash(prev, row) != h:
            return False, len(rows)
        prev = h
    return True, len(rows)


# ---------------------------------------------------------------- public API
def check(action: str, target, ctx: dict | None = None, *, policy: Policy | None = None) -> Decision:
    """Evaluate the policy for one action. Off -> allowed, silent. Audit/enforce -> audited."""
    ctx = ctx or {}
    m = mode()
    actor = str(ctx.get("actor") or "unknown")
    t = _norm(target)[:TARGET_MAX]
    if m == "off":
        return Decision(True, action, t, actor, "policy_off", "off")
    allowed, rid = evaluate(policy or load_policy(), action, _norm(target), ctx)
    d = Decision(allowed, action, t, actor, rid, m, "" if allowed else "denied by policy")
    audit("policy_allowed" if allowed else "policy_denied",
          {"actor": actor, "action": action, "target": t, "rule": rid, "mode": m,
           **{k: ctx[k] for k in CTX_KEYS if ctx.get(k) is not None}})
    return d


def require(action: str, target, ctx: dict | None = None, *, policy: Policy | None = None) -> Decision:
    """check() + raise PolicyDenied when mode=enforce and the decision is a deny (audit mode only logs)."""
    d = check(action, target, ctx, policy=policy)
    if not d.allowed and d.mode == "enforce":
        raise PolicyDenied(d)
    return d

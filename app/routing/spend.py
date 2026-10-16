"""ANAM-003: accumulated-spend ceiling for paid model calls (per run and per day).

Every paid call of the answer loop (first call, retries, escalations, fallbacks) goes through
`MeteredAdapter`: BEFORE the network it reserves the WORST-CASE cost of the call (prompt tokens
estimated pessimistically + `max_tokens` priced as output/thinking; unknown price -> pessimistic bound
from config/pricing.py) and refuses with `BudgetExceeded` when run_spent + worst > run cap or
day_spent + worst > day cap. After the call the reservation is replaced by the real usage cost.
Local providers (ollama/vllm) cost 0 and are never blocked, so benchmark runs with cost 0 are unchanged.

Env (all optional):
  ANAMNESIA_BUDGET_ENFORCE   default ON; 0/false/no/off disables the ceilings (explicit opt-out)
  ANAMNESIA_BUDGET_RUN_USD   per-run ceiling,  default 0.05
  ANAMNESIA_BUDGET_DAY_USD   per-day ceiling,  default 1.00 (process-wide accumulator, local calendar day)
An unparsable/negative value falls back to the default; "0" is a valid ceiling (blocks every paid call).
Paid calls additionally need explicit consent: ANAMNESIA_PAID_CALLS=1 (see adapters/models/errors.py).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

from app.adapters.models.errors import BudgetExceeded, is_local_provider
from config.pricing import estimate_cost

ENFORCE_ENV = "ANAMNESIA_BUDGET_ENFORCE"
RUN_ENV = "ANAMNESIA_BUDGET_RUN_USD"
DAY_ENV = "ANAMNESIA_BUDGET_DAY_USD"
DEFAULT_RUN_USD = 0.05
DEFAULT_DAY_USD = 1.00
_OFF = {"0", "false", "no", "off"}
CHARS_PER_TOKEN = 3.0   # pessimistic (real text is ~4 chars/token): overestimates input tokens


def enforce_enabled() -> bool:
    return os.environ.get(ENFORCE_ENV, "").strip().lower() not in _OFF


def _cap(env: str, default: float) -> float:
    try:
        v = float(os.environ.get(env, "").strip() or default)
    except ValueError:
        return default
    return v if v >= 0 else default


def run_cap() -> float:
    return _cap(RUN_ENV, DEFAULT_RUN_USD)


def day_cap() -> float:
    return _cap(DAY_ENV, DEFAULT_DAY_USD)


class _DayLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day = time.strftime("%Y-%m-%d")
        self._spent = 0.0

    def _roll(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._spent = today, 0.0

    def spent(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    def add(self, usd: float) -> None:
        with self._lock:
            self._roll()
            self._spent = max(0.0, self._spent + usd)

    def reset(self) -> None:
        with self._lock:
            self._day, self._spent = time.strftime("%Y-%m-%d"), 0.0


DAY = _DayLedger()


@dataclass
class RunSpend:
    """Accumulated spend of ONE run (all attempts). `reserve`/`settle` keep it monotonic and bounded."""
    spent: float = 0.0
    calls: int = 0
    blocked: list[str] = field(default_factory=list)

    def check(self, worst_usd: float, what: str = "") -> None:
        if not enforce_enabled() or worst_usd <= 0:
            return
        if self.spent + worst_usd > run_cap() + 1e-12:
            self.blocked.append(what)
            raise BudgetExceeded(f"teto por run excedido: gasto {self.spent:.6f} + pior caso {worst_usd:.6f} "
                                 f"> {run_cap():.6f} USD ({what})")
        if DAY.spent() + worst_usd > day_cap() + 1e-12:
            self.blocked.append(what)
            raise BudgetExceeded(f"teto diario excedido: gasto {DAY.spent():.6f} + pior caso {worst_usd:.6f} "
                                 f"> {day_cap():.6f} USD ({what})")

    def reserve(self, usd: float) -> None:
        self.spent += usd
        DAY.add(usd)

    def settle(self, reserved: float, actual: float) -> None:
        self.spent = max(0.0, self.spent - reserved + actual)
        DAY.add(actual - reserved)
        self.calls += 1

    def can_afford(self, worst_usd: float) -> bool:
        try:
            self.check(worst_usd)
            return True
        except BudgetExceeded:
            self.blocked.pop() if self.blocked else None
            return False


def entry_price(entry) -> dict | None:
    f = getattr(entry, "cost_per_mtok", None)
    try:
        return f() if callable(f) else None
    except Exception:  # noqa: BLE001
        return None


def worst_case_usd(entry, prompt: str, max_tokens: int) -> float:
    """Upper bound of one call: chars/3 input tokens + max_tokens at output price (covers thinking)."""
    provider = getattr(entry, "provider", None)
    if is_local_provider(provider) or getattr(entry, "local", False):
        return 0.0
    tin = int(len(prompt or "") / CHARS_PER_TOKEN) + 1
    usd, _ = estimate_cost(getattr(entry, "model", None), provider, tokens_in=tin,
                           tokens_out=int(max_tokens or 0), price=entry_price(entry))
    return usd


def actual_usd(entry, res, worst: float) -> float:
    """Real cost from usage; if the provider reported no tokens on a paid call, charge the worst case."""
    tin, tout = getattr(res, "input_tokens", None), getattr(res, "output_tokens", None)
    if tin is None or tout is None:
        return worst
    usd, _ = estimate_cost(getattr(entry, "model", None), getattr(entry, "provider", None),
                           tokens_in=int(tin), tokens_out=int(tout), price=entry_price(entry))
    return min(usd, worst) if worst else usd


class MeteredAdapter:
    """Wraps any adapter: budget check before, accounting after. Free (local) calls pass through."""

    def __init__(self, inner, entry, run: RunSpend):
        self.inner, self.entry, self.run = inner, entry, run

    def generate(self, prompt, temperature=0.0, max_tokens=800, **kw):
        # **kw carries ANAM-033 `private=True` to the real adapter (only present when set)
        worst = worst_case_usd(self.entry, prompt, max_tokens)
        if worst <= 0:
            return self.inner.generate(prompt, temperature=temperature, max_tokens=max_tokens, **kw)
        self.run.check(worst, getattr(self.entry, "id", "?"))
        self.run.reserve(worst)
        try:
            res = self.inner.generate(prompt, temperature=temperature, max_tokens=max_tokens, **kw)
        except BaseException:
            self.run.settle(worst, worst)    # unknown outcome of a network call: keep the reservation
            raise
        failed = bool(getattr(res, "error", None))
        # a failed call with no usage may still have been billed (timeouts after send): keep worst case
        self.run.settle(worst, actual_usd(self.entry, res, worst) if not failed or
                        getattr(res, "input_tokens", None) is not None else worst)
        return res

    def __getattr__(self, name):
        return getattr(self.inner, name)


def metered_factory(make_adapter_fn, run: RunSpend):
    """make_adapter-compatible factory returning metered adapters (resolves the hook at call time)."""
    def factory(entry, avail=None):
        return MeteredAdapter(make_adapter_fn(entry, avail), entry, run)
    return factory

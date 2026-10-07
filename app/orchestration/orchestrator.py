"""Deterministic sub-agent orchestrator (v1: no LLM in planning).

plan(task)  -> researcher(s) -> implementer -> reviewer. Models come from app.routing.router.route over the part of
the registry that matches the role's model CLASS (see config.py); escalation uses app.routing.escalation.next_model.
Cost is computed only from verified registry prices; otherwise it is null with status 'unavailable'.
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.orchestration.config import OrchestrationConfig, load_config
from app.orchestration.launchers import SessionLauncher
from app.orchestration.roles import contract, role_prompt
from app.orchestration.runs import TERMINAL, InvalidTransition, Run, RunError, list_runs, project_root
from app.routing.escalation import next_model
from app.routing.policy import preset as routing_preset
from app.routing.registry import Registry, load_registry
from app.routing.router import route

MAX_RESEARCHERS = 8
PRIOR_CHARS = 4000
_BULLET = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$")


@dataclass
class Step:
    step_id: str
    role: str
    text: str
    depends_on: list = field(default_factory=list)


class _Stop(Exception):
    """Internal: stop the run (state failed/cancelled) with a reason."""

    def __init__(self, state: str, reason: str):
        super().__init__(reason)
        self.state, self.reason = state, reason


def plan(task: str) -> list:
    """Researcher(s) -> implementer -> reviewer. A task with >= 2 bullet lines gets one researcher per bullet."""
    task = (task or "").strip()
    if not task:
        raise ValueError("task must not be empty")
    bullets = [m.group(1) for ln in task.splitlines() if (m := _BULLET.match(ln))]
    steps: list[Step] = []
    if len(bullets) >= 2:
        for i, b in enumerate(bullets[:MAX_RESEARCHERS], 1):
            steps.append(Step(f"researcher-{i}", "researcher", f"{b}\n\n(Context: overall task below)\n{task}"))
    else:
        steps.append(Step("researcher", "researcher", task))
    rids = [s.step_id for s in steps]
    steps.append(Step("implementer", "implementer", task, rids))
    steps.append(Step("reviewer", "reviewer", task, ["implementer"]))
    return steps


def attempt_cost(entry, tokens_in, tokens_out):
    """(cost_usd|None, status). Money only from a verified price; local models are 0.0 (registry rule)."""
    st = entry.price_status
    if st == "verified" and tokens_in is not None and tokens_out is not None:
        p = entry.price
        return (tokens_in * p.input + tokens_out * p.output) / 1_000_000, "measured"
    if st == "local_zero":
        return 0.0, "local_zero"
    return None, "unavailable"


def _sum_known(vals):
    known = [v for v in vals if v is not None]
    return (sum(known) if known else None), len(known), len(vals)


def _cost_status(known: int, total: int) -> str:
    if total == 0 or known == 0:
        return "unavailable"
    return "measured" if known == total else "partial"


class Orchestrator:
    def __init__(self, launcher: SessionLauncher, registry: Registry | None = None,
                 config: OrchestrationConfig | None = None, available_providers=None,
                 profile_id: str | None = None, sync: bool = False):
        self.launcher = launcher
        self._registry = registry
        self.config = config or load_config()
        self.available_providers = None if available_providers is None else set(available_providers)
        self.profile_id = profile_id
        self.sync = sync
        self._runs: dict[str, Run] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._sessions: dict[str, set] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ registry / model choice
    @property
    def registry(self) -> Registry:
        if self._registry is None:
            self._registry = load_registry()
        return self._registry

    def _usable(self) -> Registry:
        reg = self.registry
        if self.available_providers is None:
            return reg
        return Registry([m for m in reg.models if m.provider in self.available_providers],
                        reg.file_hash, reg.version)

    def _class_registry(self, usable: Registry, cls: str) -> Registry:
        tiers = set(self.config.class_tiers(self.registry.tiers())[cls])
        return Registry([m for m in usable.models if m.tier in tiers], usable.file_hash, usable.version)

    def select_model(self, role: str, preset_name: str, query: str) -> dict:
        """{'decision', 'class', 'effective_class', 'warnings', 'chain'}; decision.model_id None = nothing usable.

        The fallback chain is one model per class ABOVE the effective class (escalation moves up a class).
        """
        pr = self.config.preset(preset_name)
        cls = pr.roles[role]
        policy = routing_preset(pr.routing_preset, enabled=True)
        usable = self._usable()
        kind = contract(role).task_kind
        warnings: list[str] = []

        def pick(c):
            sub = self._class_registry(usable, c)
            d = route(query, 0, kind, "medium", sub, policy, self.available_providers)
            if d.model_id is None and kind != "general":
                d2 = route(query, 0, "general", "medium", sub, policy, self.available_providers)
                if d2.model_id is not None:
                    d2.reason_codes.append(f"task_kind_{kind}_unavailable_used_general")
                    return d2
            return d

        decision, eff = None, cls
        for c in self.config.classes_from(cls):
            d = pick(c)
            if d.model_id is not None:
                decision, eff = d, c
                break
        if decision is None:
            decision = pick(cls)
            return {"decision": decision, "class": cls, "effective_class": None,
                    "warnings": [f"no_model_for_class_{cls}"], "chain": []}
        if eff != cls:
            warnings.append(f"class_{cls}_has_no_connected_model_fell_to_{eff}")
        chain: list[str] = []
        for c in self.config.classes_from(eff)[1:]:
            d = pick(c)
            if d.model_id and d.model_id not in chain and d.model_id != decision.model_id:
                chain.append(d.model_id)
        decision.fallback_chain = chain
        decision.max_escalations = min(len(chain), self.config.limits.max_escalations_per_step)
        return {"decision": decision, "class": cls, "effective_class": eff, "warnings": warnings, "chain": chain}

    # ------------------------------------------------------------ public API
    def plan(self, task: str) -> list:
        return plan(task)

    def submit(self, task: str, preset: str, project_path, project_id: str | None = None,
               budget_usd: float | None = None) -> str:
        """Create the run directory and start it (background thread, or inline when sync=True). Returns run_id."""
        pr = self.config.preset(preset)            # validates the preset before touching the disk
        steps = plan(task)
        limits = self.config.limits
        budget = limits.budget_usd if budget_usd is None else budget_usd
        if budget is not None and (isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget < 0):
            raise ValueError("budget_usd must be a non-negative number or null")
        run = Run.create(project_path, task, preset, project_id=project_id, budget_usd=budget,
                         routing_preset=pr.routing_preset, registry_version=self.registry.version_hash(),
                         totals={"input_tokens": None, "output_tokens": None, "cost_usd": None,
                                 "cost_status": "unavailable"})
        run.summary["steps"] = [{"step_id": s.step_id, "role": s.role, "depends_on": s.depends_on,
                                 "state": "pending"} for s in steps]
        run.write_summary()
        with self._lock:
            self._runs[run.run_id] = run
        if self.sync:
            self._execute(run, steps)
        else:
            t = threading.Thread(target=self._execute, args=(run, steps), daemon=True, name=f"orch-{run.run_id}")
            with self._lock:
                self._threads[run.run_id] = t
            t.start()
        return run.run_id

    def run(self, task: str, preset: str, project_path, **kw) -> dict:
        """Submit and wait; returns the final summary."""
        rid = self.submit(task, preset, project_path, **kw)
        self.wait(rid)
        return self.get(rid, project_path).summary

    def wait(self, run_id: str, timeout: float | None = None) -> bool:
        t = self._threads.get(run_id)
        if t is not None:
            t.join(timeout)
            return not t.is_alive()
        return True

    def get(self, run_id: str, project_path=None) -> Run:
        with self._lock:
            r = self._runs.get(run_id)
        if r is not None:
            return r
        if project_path is None:
            raise RunError(f"run not found: {run_id}")
        return Run.load(project_path, run_id)

    def known_runs(self) -> list:
        with self._lock:
            return [dict(r.summary) for r in self._runs.values()]

    def list(self, project_path=None) -> list:
        seen = {s["run_id"]: s for s in self.known_runs()}
        if project_path is not None:
            for s in list_runs(project_path):
                seen.setdefault(s["run_id"], s)
        return sorted(seen.values(), key=lambda s: s.get("created_at", 0), reverse=True)

    def cancel(self, run_id: str, project_path=None) -> str:
        """Returns the state after the request: 'cancelled' (was planned), 'cancelling' (running) or the terminal state."""
        run = self.get(run_id, project_path)
        with run._lock:
            st = run.state
            if st in TERMINAL:
                return st
            run.cancel_event.set()
            run.event("cancel_requested")
            if st == "planned":
                run.transition("cancelled", "cancelled_by_user")
                return "cancelled"
        for sid in list(self._sessions.get(run_id, ())):
            try:
                self.launcher.close(sid)
            except Exception:  # noqa: BLE001
                pass
        return "cancelling"

    # ------------------------------------------------------------ execution
    def _execute(self, run: Run, steps: list) -> None:
        limits = self.config.limits
        ctx = {"spent": 0.0, "max_attempt": 0.0}
        lock = threading.Lock()
        try:
            with run._lock:
                if run.state == "cancelled":
                    return
                run.transition("running")
            budget = run.summary.get("budget_usd")
            workers = 1 if budget is not None else limits.max_parallel_subagents   # budget => serial, see docs
            done: set = set()
            pending = list(steps)
            while pending:
                if run.cancel_event.is_set():
                    raise _Stop("cancelled", "cancelled_by_user")
                wave = [s for s in pending if all(d in done for d in s.depends_on)]
                if not wave:
                    raise _Stop("failed", "plan_deadlock")
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futs = [(s, pool.submit(self._run_step, run, s, ctx, lock)) for s in wave]
                    errs = []
                    for s, f in futs:
                        try:
                            f.result()
                            done.add(s.step_id)
                        except _Stop as e:
                            errs.append(e)
                if errs:
                    errs.sort(key=lambda e: e.state != "cancelled")   # cancellation wins the report
                    raise errs[0]
                pending = [s for s in pending if s.step_id not in done]
            self._finalize(run)
            run.transition("done")
        except _Stop as e:
            self._finalize(run)
            self._safe_transition(run, e.state, e.reason)
        except Exception as e:  # noqa: BLE001 - never leave a run stuck in 'running'
            self._finalize(run)
            self._safe_transition(run, "failed", f"internal_error:{type(e).__name__}")

    @staticmethod
    def _safe_transition(run: Run, state: str, reason: str) -> None:
        try:
            run.transition(state, reason)
        except InvalidTransition:
            pass

    def _step_entry(self, run: Run, step_id: str) -> dict:
        for e in run.summary["steps"]:
            if e["step_id"] == step_id:
                return e
        raise KeyError(step_id)

    def _finalize(self, run: Run) -> None:
        with run._lock:
            steps = run.summary["steps"]
            tin = [s.get("input_tokens") for s in steps if s.get("state") != "pending"]
            tout = [s.get("output_tokens") for s in steps if s.get("state") != "pending"]
            costs = [s.get("cost_usd") for s in steps if s.get("state") != "pending"]
            si, ki, _ = _sum_known(tin)
            so, ko, _ = _sum_known(tout)
            sc, kc, nc = _sum_known(costs)
            run.summary["totals"] = {"input_tokens": si, "output_tokens": so, "cost_usd": sc,
                                     "cost_status": _cost_status(kc, nc)}
            run.write_summary()

    def _prior(self, run: Run, step: Step) -> str:
        parts = []
        for d in step.depends_on:
            res = run.read_result(d)
            if res:
                parts.append(f"### {d}\n{res[:PRIOR_CHARS]}")
        return "\n\n".join(parts)

    def _run_step(self, run: Run, step: Step, ctx: dict, lock: threading.Lock) -> None:
        limits = self.config.limits
        preset_name = run.summary["preset"]
        budget = run.summary.get("budget_usd")
        entry_sum = self._step_entry(run, step.step_id)
        if run.cancel_event.is_set():
            raise _Stop("cancelled", "cancelled_by_user")
        sel = self.select_model(step.role, preset_name, step.text[:2000])
        decision = sel["decision"]
        with run._lock:
            run.summary["warnings"].extend(w for w in sel["warnings"] if w not in run.summary["warnings"])
            entry_sum["state"] = "running"
            entry_sum["class"] = sel["class"]
            entry_sum["effective_class"] = sel["effective_class"]
            run.write_summary()
        if decision.model_id is None:
            self._fail_step(run, entry_sum, "no_model_available")
            raise _Stop("failed", f"no_model_available:{step.role}")
        prior = self._prior(run, step)
        sdir = run.step_dir(step.step_id)
        current = decision.model_id
        failures = escalations = 0
        attempts: list[dict] = []
        escalated_from = None
        while True:
            if run.cancel_event.is_set():
                self._fail_step(run, entry_sum, "cancelled", state="cancelled")
                raise _Stop("cancelled", "cancelled_by_user")
            model = self.registry.get(current)
            if budget is not None:
                with lock:
                    spent, mx = ctx["spent"], ctx["max_attempt"]
                if model.price_status == "unavailable":
                    self._fail_step(run, entry_sum, "budget_unenforceable_price_unavailable", attempts)
                    raise _Stop("failed", f"budget_unenforceable_price_unavailable:{model.id}")
                if spent >= budget or spent + mx > budget:
                    self._fail_step(run, entry_sum, "budget_exhausted", attempts)
                    raise _Stop("failed", f"budget_exhausted:spent={spent:.6f}:budget={budget}")
            att = self._attempt(run, step, model, sdir, prior, len(attempts) + 1)
            attempts.append(att)
            if att["cost_usd"] is not None:
                with lock:
                    ctx["spent"] += att["cost_usd"]
                    ctx["max_attempt"] = max(ctx["max_attempt"], att["cost_usd"])
            self._record(run, entry_sum, current, attempts, escalated_from)
            if budget is not None:
                with lock:
                    over = ctx["spent"] > budget
                if over:
                    self._fail_step(run, entry_sum, "budget_exceeded", attempts, keep_state=att["ok"])
                    raise _Stop("failed", f"budget_exceeded:spent={ctx['spent']:.6f}:budget={budget}")
                if att["cost_usd"] is None and model.price_status == "verified":
                    self._fail_step(run, entry_sum, "usage_not_reported_budget_unenforceable", attempts)
                    raise _Stop("failed", "usage_not_reported_budget_unenforceable")
            if att["ok"]:
                with run._lock:
                    entry_sum["state"] = "done"
                    run.write_summary()
                run.event("step_done", step=step.step_id, model_id=current, attempts=len(attempts))
                return
            failures += 1
            run.event("step_failed_attempt", step=step.step_id, model_id=current, error=att["error"],
                      failures=failures)
            if failures >= limits.escalate_on_failures:
                nxt = None
                if escalations < limits.max_escalations_per_step:
                    nxt = next_model(decision, escalations + 1)
                if nxt is None:
                    self._fail_step(run, entry_sum, att["error"] or "failed", attempts)
                    raise _Stop("failed", f"step_failed:{step.step_id}:{att['error']}")
                run.event("escalated", step=step.step_id, from_model=current, to_model=nxt,
                          after_failures=failures)
                escalated_from, current = current, nxt
                escalations += 1
                failures = 0
                with run._lock:
                    entry_sum["escalated_from"] = escalated_from
                    run.write_summary()

    def _attempt(self, run: Run, step: Step, model, sdir, prior: str, n: int) -> dict:
        limits = self.config.limits
        for name in ("result.md", "status.json"):
            f = sdir / name
            if f.exists():
                f.unlink()
        env = {
            "ANAMNESIA_RUN_ID": run.run_id, "ANAMNESIA_RUN_DIR": str(run.dir),
            "ANAMNESIA_STEP": step.step_id, "ANAMNESIA_STEP_DIR": str(sdir),
            "ANAMNESIA_ROLE": step.role, "ANAMNESIA_MODEL_ID": model.id, "ANAMNESIA_MODEL": model.model,
            "ANAMNESIA_PROVIDER": model.provider,
            "ANAMNESIA_READ_ONLY": "1" if contract(step.role).read_only else "0",
        }
        hint = (f"Write your answer to {sdir / 'result.md'} and a status.json "
                f"({{\"ok\":true,\"input_tokens\":null,\"output_tokens\":null}}) next to it.")
        text = role_prompt(step.role, step.text, prior, hint)
        run.event("attempt_start", step=step.step_id, model_id=model.id, attempt=n)
        t0 = time.perf_counter()
        sid = None
        st = None
        err = None
        try:
            sid = self.launcher.launch(run.summary.get("project_id"), self.profile_id, env,
                                       run.summary["project_path"])
            with self._lock:
                self._sessions.setdefault(run.run_id, set()).add(sid)
            self.launcher.send(sid, text)
            deadline = time.monotonic() + limits.step_timeout_s
            while True:
                st = run.read_status(step.step_id)
                if st is not None:
                    break
                if run.cancel_event.is_set():
                    err = "cancelled"
                    break
                if not self.launcher.is_alive(sid):
                    st = run.read_status(step.step_id)
                    if st is None:
                        err = "session_ended_without_result"
                    break
                if time.monotonic() > deadline:
                    err = "timeout"
                    break
                time.sleep(limits.poll_interval_s)
        except Exception as e:  # noqa: BLE001
            err = f"launcher_error:{type(e).__name__}"
        finally:
            if sid is not None:
                try:
                    self.launcher.close(sid)
                except Exception:  # noqa: BLE001
                    pass
                with self._lock:
                    self._sessions.get(run.run_id, set()).discard(sid)
        wall = (time.perf_counter() - t0) * 1000
        st = st or {}
        ok = bool(st.get("ok")) and run.read_result(step.step_id) is not None and err is None
        error = None if ok else (err or st.get("error") or "no_result")
        tin, tout = st.get("input_tokens"), st.get("output_tokens")
        cost, cstatus = attempt_cost(model, tin, tout)
        lat = st.get("latency_ms")
        att = {"attempt": n, "model_id": model.id, "ok": ok, "error": error, "input_tokens": tin,
               "output_tokens": tout, "latency_ms": lat if lat is not None else round(wall, 1),
               "cost_usd": cost, "cost_status": cstatus, "price_status": model.price_status}
        run.event("attempt_end", step=step.step_id, **{k: v for k, v in att.items() if k != "attempt"})
        return att

    def _record(self, run: Run, entry_sum: dict, current: str, attempts: list, escalated_from) -> None:
        si, _, _ = _sum_known([a["input_tokens"] for a in attempts])
        so, _, _ = _sum_known([a["output_tokens"] for a in attempts])
        sc, kc, nc = _sum_known([a["cost_usd"] for a in attempts])
        last = attempts[-1]
        with run._lock:
            entry_sum.update(model_id=current, provider=self.registry.get(current).provider,
                             price_status=last["price_status"], attempts=list(attempts),
                             input_tokens=si, output_tokens=so,
                             latency_ms=round(sum(a["latency_ms"] or 0 for a in attempts), 1),
                             cost_usd=sc, cost_status=_cost_status(kc, nc))
            if escalated_from:
                entry_sum["escalated_from"] = escalated_from
            run.write_summary()

    def _fail_step(self, run: Run, entry_sum: dict, reason: str, attempts=None, state: str = "failed",
                   keep_state: bool = False) -> None:
        with run._lock:
            if keep_state:
                entry_sum["state"] = "done"
            else:
                entry_sum["state"] = state
            entry_sum["error"] = reason
            run.write_summary()
        run.event("step_failed", step=entry_sum["step_id"], reason=reason)

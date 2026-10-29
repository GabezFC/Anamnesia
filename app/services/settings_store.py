"""Server-side persisted app settings (GET/PUT /api/settings). Stored as JSON in the `kv` table.

Pure of HTTP. The budget ceilings live in the existing `budgets` table (period day|month) so the
cost ledger and the settings screen can never disagree; `alert_pct` lives in the settings JSON.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

KV_KEY = "app_settings"
DEFAULT_ALERT_PCT = 80.0
PIPELINE_CHOICES = ("auto", "baseline", "graphify", "graphify_jev", "graphify_jev_opt")


class BudgetSettings(BaseModel):
    daily_usd: float | None = Field(None, ge=0)
    monthly_usd: float | None = Field(None, ge=0)
    alert_pct: float = Field(DEFAULT_ALERT_PCT, gt=0, le=100)


class BudgetPatch(BaseModel):
    daily_usd: float | None = Field(None, ge=0)
    monthly_usd: float | None = Field(None, ge=0)
    alert_pct: float | None = Field(None, gt=0, le=100)


class Settings(BaseModel):
    subagent_preset: dict[str, Any] = Field(default_factory=dict)
    prefilter_cache: dict[str, Any] = Field(default_factory=dict)
    workspace_layout: dict[str, Any] = Field(default_factory=dict)  # X04: antes `terminal_layout`
    language: Literal["pt-BR", "en"] = "pt-BR"
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    max_tokens_per_query: int | None = Field(None, ge=1, le=1_000_000)
    default_pipeline: Literal[PIPELINE_CHOICES] = "auto"  # type: ignore[valid-type]
    auto_graphify_jev_opt: bool = False
    reduce_max_results_by_question_type: bool = False
    # ANA-202: limiares (% de piora) dos alertas de regressão; chaves de app.services.dashboard_insights
    regression_thresholds: dict[str, float] = Field(default_factory=dict)


class SettingsPatch(BaseModel):
    """Every field optional; only the ones present in the request body are applied."""
    model_config = {"extra": "forbid"}
    subagent_preset: dict[str, Any] | None = None
    prefilter_cache: dict[str, Any] | None = None
    workspace_layout: dict[str, Any] | None = None
    terminal_layout: dict[str, Any] | None = None  # alias deprecado de workspace_layout (aceito por ≥1 versão)
    language: Literal["pt-BR", "en"] | None = None
    budget: BudgetPatch | None = None
    max_tokens_per_query: int | None = Field(None, ge=1, le=1_000_000)  # explicit null clears the cap
    default_pipeline: Literal[PIPELINE_CHOICES] | None = None  # type: ignore[valid-type]
    auto_graphify_jev_opt: bool | None = None
    reduce_max_results_by_question_type: bool | None = None
    regression_thresholds: dict[str, float] | None = None

    @field_validator("regression_thresholds")
    @classmethod
    def _known_thresholds(cls, v):
        if v is None:
            return v
        from app.services.dashboard_insights import DEFAULT_THRESHOLDS
        bad = sorted(set(v) - set(DEFAULT_THRESHOLDS))
        if bad or any(x < 0 or x > 1000 for x in v.values()):
            raise ValueError(f"limiares inválidos: use {sorted(DEFAULT_THRESHOLDS)} com valores 0..1000 (chaves ruins: {bad})")
        return v


def _stored(db) -> dict:
    raw = db.get_kv(KV_KEY)
    return raw if isinstance(raw, dict) else {}


def _migrate_layout_key(db, stored: dict) -> dict:
    """X04: `terminal_layout` -> `workspace_layout`. Só o nome antigo no armazenamento: copia o dado para o novo
    nome e persiste (sem perder nada). Os dois presentes: o novo vence e o antigo é descartado."""
    if "terminal_layout" not in stored:
        return stored
    migrated = {k: v for k, v in stored.items() if k != "terminal_layout"}
    if "workspace_layout" not in migrated and isinstance(stored["terminal_layout"], dict):
        migrated["workspace_layout"] = stored["terminal_layout"]
    try:
        db.set_kv(KV_KEY, migrated)
    except Exception:  # noqa: BLE001 - leitura nunca falha por causa da migração; tenta de novo na próxima
        pass
    return migrated


def load_settings(db) -> Settings:
    """Stored settings (invalid/legacy keys ignored -> defaults) with the live budget ceilings."""
    raw = dict(_migrate_layout_key(db, _stored(db)))
    raw.pop("budget_ceilings", None)
    try:
        s = Settings.model_validate(raw)
    except Exception:  # noqa: BLE001 - a corrupt row must never break the app: fall back to defaults
        s = Settings()
    ceilings = db.get_budgets()
    s.budget.daily_usd = ceilings.get("day")
    s.budget.monthly_usd = ceilings.get("month")
    return s


def save_patch(db, patch: SettingsPatch) -> Settings:
    """Merge `patch` (only fields_set) into the stored settings and persist. Returns the result."""
    current = load_settings(db).model_dump()
    sent = set(patch.model_fields_set)
    if "terminal_layout" in sent:  # alias deprecado: vale como workspace_layout, salvo se o novo nome também veio
        if "workspace_layout" not in sent:
            patch = patch.model_copy(update={"workspace_layout": patch.terminal_layout})
            sent.add("workspace_layout")
        sent.discard("terminal_layout")
    for key in sent:
        if key == "budget":
            continue
        value = getattr(patch, key)
        if value is None and key not in ("max_tokens_per_query",):
            continue  # null only means "clear" for the nullable cap; other fields ignore null
        current[key] = value
    if "budget" in sent and patch.budget is not None:
        bsent = patch.budget.model_fields_set
        if "daily_usd" in bsent:
            db.set_budget("day", patch.budget.daily_usd)
            current["budget"]["daily_usd"] = patch.budget.daily_usd
        if "monthly_usd" in bsent:
            db.set_budget("month", patch.budget.monthly_usd)
            current["budget"]["monthly_usd"] = patch.budget.monthly_usd
        if "alert_pct" in bsent and patch.budget.alert_pct is not None:
            current["budget"]["alert_pct"] = patch.budget.alert_pct
    final = Settings.model_validate(current)
    stored = final.model_dump()
    stored["budget"] = {"alert_pct": final.budget.alert_pct}  # ceilings live in `budgets`
    db.set_kv(KV_KEY, stored)
    return load_settings(db)


def alert_pct(db) -> float:
    b = _stored(db).get("budget")
    try:
        v = float(b.get("alert_pct", DEFAULT_ALERT_PCT)) if isinstance(b, dict) else DEFAULT_ALERT_PCT
    except (TypeError, ValueError):
        return DEFAULT_ALERT_PCT
    return v if 0 < v <= 100 else DEFAULT_ALERT_PCT


def economy_of(db):
    """The three economy opt-ins, read raw (cheap, tolerant). Absent/invalid -> everything off."""
    from app.gateway.economy import EconomySettings
    raw = _stored(db)
    cap = raw.get("max_tokens_per_query")
    return EconomySettings(
        auto_graphify_jev_opt=raw.get("auto_graphify_jev_opt") is True,
        reduce_max_results_by_question_type=raw.get("reduce_max_results_by_question_type") is True,
        max_tokens_per_query=cap if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0 else None)


def default_pipeline_of(db) -> str:
    v = _stored(db).get("default_pipeline")
    return v if v in PIPELINE_CHOICES else "auto"

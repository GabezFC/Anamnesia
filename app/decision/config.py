"""Configuração do Decision Engine (ANAM-043): limiares SEPARADOS por provider e por projeto.

Fontes (ordem): padrões dos configs existentes (JevConfig/LayaConfig) < preset < arquivo JSON
(`MG_DECISION_CONFIG_FILE`) < variáveis `MG_DECISION_*`. Limiares são EXPERIMENTAIS: recalibre com os seus dados.

Isolamento por projeto: `projects.<slug>` só vale para requisições com `project == slug`. Não há herança entre
projetos; projeto sem entrada usa os limiares globais e isso é reportado (`project_config: "default"`).
Nada aqui lê o vault.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

PROVIDERS = ("jev", "laya", "hybrid", "adaptive")
STRATEGIES = ("laya_then_jev", "jev_then_laya", "ensemble")
THRESHOLD_KEYS = ("jev", "laya", "ensemble", "adaptive")
DEFAULT_PROVIDER = "jev"   # JEV-only (graphify_jev_opt) continua o padrão; Laya/híbridos são opt-in

# Presets: SÓ configuração, EXPERIMENTAIS (nenhum foi validado com JEV real; ver docs/bench/decision-engine.md).
PRESETS: dict[str, dict] = {
    "fast":     {"provider": "laya", "strategy": "laya_then_jev",
                 "note": "só Laya (zero JEV); pior relevância medida no corpus sintético"},
    "balanced": {"provider": "adaptive", "strategy": "laya_then_jev",
                 "note": "Laya primeiro, JEV só com confidence baixa"},
    "quality":  {"provider": "hybrid", "strategy": "ensemble",
                 "note": "Laya e JEV em todos; custo JEV igual ao JEV-only"},
}


@dataclass(frozen=True)
class Thresholds:
    keep: float
    review: float
    min_confidence: float = 0.0

    def validate(self, where: str = "") -> "Thresholds":
        if not (0.0 <= self.review <= self.keep <= 1.0):
            raise ValueError(f"limiares inválidos{where}: exige 0 <= review <= keep <= 1")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence inválido{where}: exige 0..1")
        return self

    def band(self, p: float | None) -> str:
        if p is None:
            return "UNJUDGED"
        return "KEEP" if p >= self.keep else ("REVIEW" if p >= self.review else "DROP")

    def to_dict(self) -> dict:
        return {"keep": self.keep, "review": self.review, "min_confidence": self.min_confidence}


def _th(d: dict, base: Thresholds, where: str) -> Thresholds:
    return Thresholds(float(d.get("keep", base.keep)), float(d.get("review", base.review)),
                      float(d.get("min_confidence", base.min_confidence))).validate(where)


def _builtin_thresholds() -> dict[str, Thresholds]:
    from config.jev import JevConfig
    from config.laya import LayaConfig
    j, ly = JevConfig(), LayaConfig()
    return {"jev": Thresholds(j.relevance_threshold, j.review_threshold),
            "laya": Thresholds(ly.keep_threshold, ly.drop_threshold, ly.min_confidence),
            # ensemble opera sobre o voto (KEEP=1, REVIEW=.5, DROP=0), sem escala de probabilidade
            "ensemble": Thresholds(0.75, 0.25),
            # adaptive: faixas do Laya + confidence mínima abaixo da qual o item vai ao JEV (EXPERIMENTAL; ver bench)
            "adaptive": Thresholds(ly.keep_threshold, ly.drop_threshold, 0.05)}


@dataclass
class DecisionConfig:
    provider: str = DEFAULT_PROVIDER
    strategy: str = "laya_then_jev"
    preset: str = ""
    thresholds: dict[str, Thresholds] = field(default_factory=_builtin_thresholds)
    ensemble_weights: tuple[float, float] = (0.5, 0.5)       # (laya, jev)
    projects: dict[str, dict] = field(default_factory=dict)  # slug -> {"provider"?, "strategy"?, "thresholds": {...}}
    review_action: str = "keep"
    cache_size: int = 2048
    history_size: int = 500
    history_persist: bool = True
    source: str = "defaults"

    def validate(self) -> "DecisionConfig":
        if self.provider not in PROVIDERS:
            raise ValueError(f"MG_DECISION_PROVIDER inválido: {self.provider!r} ({'|'.join(PROVIDERS)})")
        if self.strategy not in STRATEGIES:
            raise ValueError(f"MG_DECISION_STRATEGY inválido: {self.strategy!r} ({'|'.join(STRATEGIES)})")
        if self.preset and self.preset not in PRESETS:
            raise ValueError(f"MG_DECISION_PRESET inválido: {self.preset!r} ({'|'.join(PRESETS)})")
        if self.review_action not in ("keep", "drop"):
            raise ValueError("review_action: keep|drop")
        for k, t in self.thresholds.items():
            t.validate(f" ({k})")
        for slug, p in self.projects.items():
            if p.get("provider", self.provider) not in PROVIDERS:
                raise ValueError(f"projects.{slug}.provider inválido")
            if p.get("strategy", self.strategy) not in STRATEGIES:
                raise ValueError(f"projects.{slug}.strategy inválida")
        return self

    # -- resolução por projeto (isolamento explícito) ---------------------------------------------
    def project_entry(self, project: str) -> dict | None:
        return self.projects.get(project) if project else None

    def provider_for(self, project: str = "") -> tuple[str, str]:
        e = self.project_entry(project) or {}
        return e.get("provider", self.provider), e.get("strategy", self.strategy)

    def thresholds_for(self, which: str, project: str = "") -> Thresholds:
        base = self.thresholds[which]
        e = self.project_entry(project)
        if e and which in (e.get("thresholds") or {}):
            return _th(e["thresholds"][which], base, f" (projects.{project}.{which})")
        return base

    def policy_hash(self, project: str = "") -> str:
        """Entra na chave de cache: muda quando limiares/estratégia/pesos/política de fallback mudam."""
        prov, strat = self.provider_for(project)
        blob = json.dumps({"p": prov, "s": strat, "w": self.ensemble_weights, "r": self.review_action,
                           "t": {k: self.thresholds_for(k, project).to_dict() for k in THRESHOLD_KEYS}},
                          sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def to_public(self) -> dict:
        """Config efetiva (sem segredos: aqui não há chaves). Projetos listados por slug, sem conteúdo."""
        return {"provider": self.provider, "strategy": self.strategy, "preset": self.preset or None,
                "preset_status": "EXPERIMENTAL" if self.preset else None,
                "thresholds": {k: v.to_dict() for k, v in self.thresholds.items()},
                "threshold_label": "ESTIMATED (experimental, calibrado no corpus sintético; recalibre)",
                "ensemble_weights": {"laya": self.ensemble_weights[0], "jev": self.ensemble_weights[1]},
                "projects": {s: {"provider": p.get("provider"), "strategy": p.get("strategy"),
                                 "thresholds": {k: _th(v, self.thresholds[k], "").to_dict()
                                                for k, v in (p.get("thresholds") or {}).items()}}
                             for s, p in self.projects.items()},
                "review_action": self.review_action, "cache_size": self.cache_size,
                "history_size": self.history_size, "history_persist": self.history_persist,
                "fallback_policy": FALLBACK_POLICY, "source": self.source}


FALLBACK_POLICY = {"retrieval": "allow (passa, sinalizado fallback=true)", "memory": "REVIEW",
                   "security": "fail-closed (QUARANTINE)"}


def load_config(env: dict | None = None) -> DecisionConfig:
    import os

    def _env_str(name: str, default: str = "") -> str:  # leitura injetável (testes); nome literal p/ gen_config_reference
        v = os.environ.get(name) if env is None else env.get(name)
        return (default if v is None else v).strip()

    cfg = DecisionConfig()
    src = ["defaults"]
    preset = _env_str("MG_DECISION_PRESET").lower()
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"MG_DECISION_PRESET inválido: {preset!r} ({'|'.join(PRESETS)})")
        cfg.preset, cfg.provider, cfg.strategy = preset, PRESETS[preset]["provider"], PRESETS[preset]["strategy"]
        src.append(f"preset:{preset}")
    path = _env_str("MG_DECISION_CONFIG_FILE")
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for k, v in (data.get("thresholds") or {}).items():
            if k not in THRESHOLD_KEYS:
                raise ValueError(f"thresholds.{k}: provider desconhecido ({'|'.join(THRESHOLD_KEYS)})")
            cfg.thresholds[k] = _th(v, cfg.thresholds[k], f" (thresholds.{k})")
        w = data.get("ensemble_weights")
        if w:
            cfg.ensemble_weights = (float(w.get("laya", 0.5)), float(w.get("jev", 0.5)))
        cfg.projects = {str(s): dict(p) for s, p in (data.get("projects") or {}).items()}
        cfg.review_action = data.get("review_action", cfg.review_action)
        src.append("file")
    if _env_str("MG_DECISION_PROVIDER"):
        cfg.provider = _env_str("MG_DECISION_PROVIDER").lower()
        src.append("env")
    if _env_str("MG_DECISION_STRATEGY"):
        cfg.strategy = _env_str("MG_DECISION_STRATEGY").lower()
    cfg.cache_size = max(0, int(_env_str("MG_DECISION_CACHE_SIZE", "2048")))
    cfg.history_size = max(10, int(_env_str("MG_DECISION_HISTORY_SIZE", "500")))
    cfg.history_persist = _env_str("MG_DECISION_HISTORY_PERSIST", "1").lower() in ("1", "true", "yes", "on")
    cfg.source = "+".join(src)
    return cfg.validate()


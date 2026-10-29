"""Fase 2B (config): presets, isolamento por projeto e invalidação do cache, em processo (sem rede, sem gateway).

    .venv/Scripts/python.exe scripts/archive/audit_models_2026_10_16_cfg.py   # imprime JSON e grava a chave "config" no raw JSON
"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.decision.cache import cache_key
from app.decision.config import load_config

out = {"label": "MEASURED (in-process: app.decision.config.load_config / cache_key)"}
out["presets"] = {}
for pr in ("", "fast", "balanced", "quality"):
    c = load_config(env={"MG_DECISION_PRESET": pr} if pr else {})
    out["presets"][pr or "(nenhum)"] = {"provider": c.provider, "strategy": c.strategy, "preset": c.preset or None,
                                         "review_action": c.review_action, "policy_hash": c.policy_hash()}
cfgfile = {"projects": {"alfa": {"provider": "laya", "thresholds": {"laya": {"keep": 0.9, "review": 0.5}}},
                         "beta": {"provider": "hybrid", "strategy": "ensemble", "thresholds": {"laya": {"keep": 0.1, "review": 0.02}}}}}
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
    json.dump(cfgfile, f)
c = load_config(env={"MG_DECISION_CONFIG_FILE": f.name})
os.unlink(f.name)
out["isolamento"] = {p: {"provider_strategy": c.provider_for(p), "laya": c.thresholds_for("laya", p).to_dict(),
                         "policy_hash": c.policy_hash(p)} for p in ("alfa", "beta", "gama", "")}
base = dict(op="retrieval", project="p", provider="laya", strategy="", query="q", content_hash="h", schema="relevance-v1",
            checkpoint="ck1", version="v1", policy="pol1")
k0 = cache_key(**base)
out["cache_key"] = {"igual_repetido": cache_key(**base) == k0}
for fld, val in (("checkpoint", "ck2"), ("version", "v2"), ("schema", "relevance-v2"), ("policy", "pol2"), ("project", "p2"),
                 ("provider", "jev"), ("query", "q2"), ("content_hash", "h2"), ("op", "memory")):
    out["cache_key"]["muda_" + fld] = cache_key(**{**base, fld: val}) != k0
print(json.dumps(out, ensure_ascii=False, indent=1))
RAW = "data/reports-out/auditoria-modelos-2026-10-16.json"
d = json.load(open(RAW, encoding="utf-8")); d["config"] = out
json.dump(d, open(RAW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

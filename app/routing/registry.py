"""Model Registry: single source (config/models.yaml) for Connections, Config and benchmark.

Rules: prices only when verified (price needs source_url + checked_at, else RegistryError);
cloud model with price null => price_status 'unavailable'; local providers cost 0.0 (config/pricing.py).
The number of tiers comes from the file. PyYAML is NOT a dependency, so a tiny YAML-subset
parser is used (maps, lists of maps, inline [a, b] lists, scalars, # comments).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from config.pricing import LOCAL_PROVIDERS, price_for

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "models.yaml"
PROVIDERS = {"ollama", "vllm", "openai", "anthropic", "openrouter", "huggingface", "nvidia"}
_KEY = r"[A-Za-z0-9_.\-]+"


class RegistryError(ValueError):
    pass


# ---------------------------------------------------------------- mini YAML
def _scalar(s: str):
    s = s.strip()
    if s in ("", "null", "~", "Null", "NULL"):
        return None
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(p) for p in inner.split(",")] if inner else []
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+|\d+)([eE][-+]?\d+)?", s):
        return float(s)
    return s


def _strip_comment(line: str) -> str:
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i]
    return line


def _parse_yaml(text: str):
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise RegistryError(f"line {n}: tabs not allowed for indentation")
        body = _strip_comment(raw).rstrip()
        if body.strip():
            lines.append((n, len(body) - len(body.lstrip()), body.strip()))
    pos = 0

    def is_item(content: str) -> bool:
        return content.startswith("- ") or content == "-"

    def block(indent: int):
        n, ind, content = lines[pos]
        if ind != indent:
            raise RegistryError(f"line {n}: bad indentation")
        return seq(indent) if is_item(content) else mapping(indent)

    def split_kv(n, content):
        m = re.match(rf"^({_KEY}):(?:\s+(.*))?$", content)
        if not m:
            raise RegistryError(f"line {n}: expected 'key: value', got {content!r}")
        return m.group(1), m.group(2)

    def mapping(indent: int, first=None):
        nonlocal pos
        out = {}
        while first is not None or pos < len(lines):
            if first is not None:
                n, content = first
                first = None
            else:
                n, ind, content = lines[pos]
                if ind < indent or (ind == indent and is_item(content)):
                    break
                if ind > indent:
                    raise RegistryError(f"line {n}: unexpected indentation")
                pos += 1
            k, v = split_kv(n, content)
            if k in out:
                raise RegistryError(f"line {n}: duplicate key {k!r}")
            if v is None:
                if pos < len(lines) and lines[pos][1] > indent:
                    out[k] = block(lines[pos][1])
                elif pos < len(lines) and lines[pos][1] == indent and is_item(lines[pos][2]):
                    out[k] = seq(indent)
                else:
                    out[k] = None
            else:
                out[k] = _scalar(v)
        return out

    def seq(indent: int):
        nonlocal pos
        out = []
        while pos < len(lines):
            n, ind, content = lines[pos]
            if ind != indent or not is_item(content):
                break
            pos += 1
            item = content[2:].strip()
            if re.match(rf"^{_KEY}:(\s|$)", item):
                out.append(mapping(indent + 2, first=(n, item)))
            else:
                out.append(_scalar(item))
        return out

    if not lines:
        return {}
    res = block(lines[0][1])
    if pos < len(lines):
        raise RegistryError(f"line {lines[pos][0]}: could not parse")
    return res


# ---------------------------------------------------------------- dataclasses
@dataclass(frozen=True)
class Price:
    input: float
    output: float
    source_url: str
    checked_at: str


@dataclass(frozen=True)
class ModelEntry:
    id: str
    provider: str
    model: str
    tier: int
    context_window: int | None = None
    capabilities: tuple[str, ...] = ()
    effort_supported: bool = False
    price: Price | None = None
    local: bool = False
    verified: bool = False

    @property
    def price_status(self) -> str:
        if self.price is not None:
            return "verified"
        if self.local:
            return "local_zero"
        return "unavailable"

    def cost_per_mtok(self) -> dict[str, float] | None:
        """Verified price, 0.0 for local, None when unavailable."""
        if self.price is not None:
            return {"input": self.price.input, "output": self.price.output}
        if self.local:
            return price_for(self.model, "ollama")
        return None

    def _sort_cost(self) -> tuple[int, float]:
        c = self.cost_per_mtok()
        return (1, 0.0) if c is None else (0, c["input"] + c["output"])


@dataclass
class Registry:
    models: list[ModelEntry] = field(default_factory=list)
    file_hash: str = ""
    version: int | str | None = None

    def get(self, model_id: str) -> ModelEntry:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(f"unknown model id: {model_id}")

    def tiers(self) -> list[int]:
        return sorted({m.tier for m in self.models})

    def price_status(self, model_id: str) -> str:
        return self.get(model_id).price_status

    def version_hash(self) -> str:
        return self.file_hash

    def eligible(self, min_tier=None, capabilities=(), min_context=None,
                 available_providers=None) -> list[ModelEntry]:
        caps = set(capabilities)
        avail = None if available_providers is None else set(available_providers)
        out = []
        for m in self.models:
            if min_tier is not None and m.tier < min_tier:
                continue
            if not caps <= set(m.capabilities):
                continue
            if min_context is not None and (m.context_window is None or m.context_window < min_context):
                continue
            if avail is not None and m.provider not in avail:
                continue
            out.append(m)
        return sorted(out, key=lambda m: (m.tier, m._sort_cost(), m.id))


# ---------------------------------------------------------------- loader
def _num(v, where, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise RegistryError(f"{where}: price.{name} must be a number, got {v!r}")
    if v < 0:
        raise RegistryError(f"{where}: price.{name} must not be negative ({v})")
    return float(v)


def _entry(raw, idx) -> ModelEntry:
    if not isinstance(raw, dict):
        raise RegistryError(f"models[{idx}]: must be a mapping")
    mid = raw.get("id")
    if not isinstance(mid, str) or not mid:
        raise RegistryError(f"models[{idx}]: missing id")
    w = f"model {mid!r}"
    provider = raw.get("provider")
    if provider not in PROVIDERS:
        raise RegistryError(f"{w}: unknown provider {provider!r} (allowed: {sorted(PROVIDERS)})")
    model = raw.get("model")
    if not isinstance(model, str) or not model:
        raise RegistryError(f"{w}: missing model")
    tier = raw.get("tier")
    if isinstance(tier, bool) or not isinstance(tier, int):
        raise RegistryError(f"{w}: tier must be an integer, got {tier!r}")
    cw = raw.get("context_window")
    if cw is not None and (isinstance(cw, bool) or not isinstance(cw, int) or cw <= 0):
        raise RegistryError(f"{w}: context_window must be a positive int or null")
    caps = raw.get("capabilities") or []
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        raise RegistryError(f"{w}: capabilities must be a list of strings")
    for key in ("effort_supported", "local", "verified"):
        if key in raw and not isinstance(raw[key], bool):
            raise RegistryError(f"{w}: {key} must be true/false")
    local = raw.get("local", provider == "ollama")
    if provider == "ollama" and not local:
        raise RegistryError(f"{w}: ollama models must have local: true")
    price = None
    p = raw.get("price")
    if p is not None:
        if not isinstance(p, dict):
            raise RegistryError(f"{w}: price must be a mapping or null")
        src, chk = p.get("source_url"), p.get("checked_at")
        if not src or not chk:
            raise RegistryError(f"{w}: price requires source_url and checked_at (unverified prices are not allowed)")
        try:
            date.fromisoformat(str(chk))
        except ValueError:
            raise RegistryError(f"{w}: price.checked_at must be YYYY-MM-DD, got {chk!r}") from None
        price = Price(_num(p.get("input"), w, "input"), _num(p.get("output"), w, "output"), str(src), str(chk))
    return ModelEntry(mid, provider, model, tier, cw, tuple(caps),
                      bool(raw.get("effort_supported", False)), price, bool(local),
                      bool(raw.get("verified", False)))


def load_registry(path=None) -> Registry:
    p = Path(path) if path else DEFAULT_PATH
    try:
        data = p.read_bytes()
    except OSError as e:
        raise RegistryError(f"cannot read registry {p}: {e}") from e
    doc = _parse_yaml(data.decode("utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("models"), list):
        raise RegistryError("registry must have a top-level 'models' list")
    models, seen = [], set()
    for i, raw in enumerate(doc["models"]):
        e = _entry(raw, i)
        if e.id in seen:
            raise RegistryError(f"duplicate model id {e.id!r}")
        seen.add(e.id)
        models.append(e)
    return Registry(models, hashlib.sha256(data).hexdigest(), doc.get("version"))

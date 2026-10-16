"""ANAM-028 / AUD-042,043: contraste WCAG 1.4.3 dos pares de tokens (frontend/css/tokens.css).

Calcula 92 pares (46 por tema) e compara ANTES (git ref, padrão HEAD) x DEPOIS (arquivo atual).
Uso:
    python scripts/check_contrast.py                 # tabela antes x depois; exit 1 se algum par DEPOIS < 4,5
    python scripts/check_contrast.py --ref HEAD --markdown docs/bench/anam-028-contraste.md
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = "frontend/css/tokens.css"
MIN_RATIO = 4.5

BG_TEXT = ["bg-app", "bg-canvas", "bg-surface", "bg-surface-elevated", "bg-surface-subtle", "bg-surface-hover"]
# (fg, bg) fixos além do produto texto x fundos
PAIRS_EXTRA = [
    ("primary", "bg-surface"), ("primary", "bg-app"),
    ("primary-text", "primary"), ("primary-text", "primary-hover"),
    ("success", "bg-surface"), ("warning", "bg-surface"), ("danger", "bg-surface"), ("info", "bg-surface"),
    ("success-text", "success-muted"), ("warning-text", "warning-muted"), ("danger-text", "danger-muted"),
    ("lab-accent", "bg-surface"), ("chart-axis-text", "bg-surface"),
    ("chart-tooltip-text", "chart-tooltip-bg"), ("chart-tooltip-muted", "chart-tooltip-bg"),
    ("term-muted", "term-header-bg"), ("term-muted", "term-bg"),
] + [(f"chart-{i}", "bg-surface") for i in range(1, 9)]
PAIRS = [(f, b) for f in ("text-primary", "text-secondary", "text-tertiary", "text-muted") for b in BG_TEXT] + PAIRS_EXTRA


def parse_block(css: str, selector: str) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, flags=re.S)
    body = m.group(1) if m else ""
    return {k: v.strip() for k, v in re.findall(r"--([\w-]+)\s*:\s*([^;]+);", body)}


def parse_themes(css: str) -> dict[str, dict[str, str]]:
    light = parse_block(css, ':root, [data-theme="light"]')
    dark = {**light, **parse_block(css, '[data-theme="dark"]')}
    return {"light": light, "dark": dark}


def to_rgba(value: str) -> tuple[float, float, float, float]:
    value = value.split("/*")[0].strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0
    m = re.fullmatch(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+))?\s*\)", value)
    if m:
        return float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4) or 1)
    raise ValueError(f"cor não suportada: {value!r}")


def flatten(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3))


def luminance(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# Tokens novos: no ANTES o CSS usava estes (o par é medido com a cor que realmente era aplicada).
LEGACY_ALIAS = {"term-muted": "text-tertiary", "chart-tooltip-muted": "text-muted"}


def ratio(theme: dict[str, str], fg_name: str, bg_name: str) -> float:
    fg_name = fg_name if fg_name in theme else LEGACY_ALIAS[fg_name]
    canvas = to_rgba(theme["bg-canvas"])[:3]
    bg = flatten(to_rgba(theme[bg_name]), canvas)           # fundo translúcido sobre o canvas
    fg = flatten(to_rgba(theme[fg_name]), bg)               # texto translúcido sobre o fundo
    l1, l2 = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def compute(css: str) -> dict[tuple[str, str, str], float]:
    out = {}
    for tname, theme in parse_themes(css).items():
        for fg, bg in PAIRS:
            out[(tname, fg, bg)] = ratio(theme, fg, bg)
    return out


def git_show(ref: str) -> str:
    r = subprocess.run(["git", "show", f"{ref}:{TOKENS}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit(f"git show falhou: {r.stderr.strip()}")
    return r.stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD", help="ref git do ANTES (padrão HEAD)")
    ap.add_argument("--markdown", help="grava relatório em Markdown")
    args = ap.parse_args(argv)
    before = compute(git_show(args.ref))
    after = compute((ROOT / TOKENS).read_text(encoding="utf-8"))
    fb = sum(1 for v in before.values() if v < MIN_RATIO)
    fa = sum(1 for v in after.values() if v < MIN_RATIO)
    lines = [f"Pares: {len(after)} | reprovam antes ({args.ref}): {fb} | reprovam depois: {fa} (mín. {MIN_RATIO}:1)", ""]
    lines.append("| tema | fg | bg | antes | depois | status |")
    lines.append("|---|---|---|---:|---:|---|")
    for key in after:
        b, a = before[key], after[key]
        if b < MIN_RATIO or a < MIN_RATIO:
            st = "OK (corrigido)" if a >= MIN_RATIO else "FALHA"
            lines.append(f"| {key[0]} | {key[1]} | {key[2]} | {b:.2f} | {a:.2f} | {st} |")
    text = "\n".join(lines)
    print(text)
    if args.markdown:
        p = ROOT / args.markdown
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# ANAM-028 — contraste (antes × depois)\n\nGerado por `scripts/check_contrast.py`.\n\n" + text + "\n", encoding="utf-8")
    return 1 if fa else 0


if __name__ == "__main__":
    sys.exit(main())

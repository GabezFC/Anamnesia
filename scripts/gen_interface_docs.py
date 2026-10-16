"""Gera docs/INTERFACES.md a partir do código (ANA-063): REST (OpenAPI), CLIs (argparse) e MCP (list_tools).

    python scripts/gen_interface_docs.py            # reescreve docs/INTERFACES.md
    python scripts/gen_interface_docs.py --check    # exit 1 se o arquivo estiver desatualizado

Nada é escrito à mão: README e demais docs só linkam para o arquivo gerado.
`tests/test_docs_interfaces.py` falha quando o arquivo diverge do código.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "INTERFACES.md"
sys.path.insert(0, str(ROOT))

# Variantes do servidor MCP (as tools dependem de variáveis lidas no import do módulo).
MCP_VARIANTS = (
    ("padrão (`MG_MCP_TOOLSET=minimal`)", {"MG_MCP_TOOLSET": "minimal", "MG_MCP_SAVE": "0"}),
    ("`MG_MCP_TOOLSET=full`", {"MG_MCP_TOOLSET": "full", "MG_MCP_SAVE": "0"}),
    ("`MG_MCP_SAVE=1` (opt-in)", {"MG_MCP_TOOLSET": "minimal", "MG_MCP_SAVE": "1"}),
    ("`MG_MCP_DECISION=1` (opt-in)", {"MG_MCP_TOOLSET": "minimal", "MG_MCP_SAVE": "0", "MG_MCP_DECISION": "1"}),
)

_MCP_PROBE = r"""
import asyncio, json
import app.mcp.server as m
tools = asyncio.run(m.server.list_tools())
out = []
for t in tools:
    sch = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
    out.append({"name": t.name, "description": (t.description or ""), "schema": sch})
print("@@JSON@@" + json.dumps(out))
"""


def _md(s: str) -> str:
    return " ".join(str(s).split()).replace("|", "\\|")


# ---------------------------------------------------------------- REST
def rest_section() -> list[str]:
    from app.main import create_app

    spec = create_app().openapi()
    rows = []
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method not in {"get", "post", "put", "delete", "patch"}:
                continue
            params = [p["name"] + ("" if p.get("required") else "?") for p in op.get("parameters", [])]
            body = "sim" if op.get("requestBody") else ""
            summary = op.get("summary") or ""
            rows.append((path, method.upper(), (op.get("tags") or [""])[0], ", ".join(params), body, summary))
    rows.sort()
    out = [f"## REST (OpenAPI {spec['openapi']}, {len(rows)} operações)", "",
           "Fonte: `app.main.create_app().openapi()`; no servidor, `/docs` e `/openapi.json`. "
           "`?` = parâmetro opcional.", "",
           "| Método | Caminho | Parâmetros | Corpo | Resumo |", "| --- | --- | --- | --- | --- |"]
    for path, method, _tag, params, body, summary in rows:
        out.append(f"| {method} | `{path}` | {_md(params) or '—'} | {body or '—'} | {_md(summary)} |")
    return out + [""]


# ---------------------------------------------------------------- argparse
def _subparsers(parser: argparse.ArgumentParser):
    for a in parser._actions:  # noqa: SLF001 - não há API pública para listar subcomandos
        if isinstance(a, argparse._SubParsersAction):  # noqa: SLF001
            return a
    return None


def _arg_row(a: argparse.Action) -> str | None:
    if isinstance(a, (argparse._HelpAction, argparse._SubParsersAction)):  # noqa: SLF001
        return None
    name = ", ".join(a.option_strings) if a.option_strings else a.dest
    extra = []
    if a.choices:
        extra.append("choices: " + "/".join(map(str, a.choices)))
    if a.default not in (None, argparse.SUPPRESS, False):
        extra.append(f"default: {a.default}")
    if not a.option_strings:
        extra.append("posicional")
    return f"| `{name}` | {_md(a.help or '')} | {_md('; '.join(extra)) or '—'} |"


def cli_section(title: str, prog: str, parser: argparse.ArgumentParser) -> list[str]:
    sp = _subparsers(parser)
    names = list(sp.choices) if sp else []
    out = [f"### {title}", "", f"`{prog}` — {len(names)} subcomandos: " + ", ".join(f"`{n}`" for n in names), ""]
    for name in names:
        sub = sp.choices[name]  # type: ignore[union-attr]
        helptext = next((a.help for a in sp._choices_actions if a.dest == name), None)  # type: ignore[union-attr] # noqa: SLF001
        out.append(f"#### `{prog} {name}`" + (f" — {_md(helptext)}" if helptext else ""))
        rows = [r for r in (_arg_row(a) for a in sub._actions) if r]  # noqa: SLF001
        if rows:
            out += ["", "| Argumento | Ajuda | Detalhes |", "| --- | --- | --- |", *rows]
        out.append("")
    return out


def cli_sections() -> list[str]:
    from anamnesia.cli import build_parser as anamnesia_parser
    from app.cli.main import build_parser as mg_parser

    return ["## CLI", "", *cli_section("memory_gateway", "python -m memory_gateway", mg_parser()),
            *cli_section("anamnesia", "anamnesia", anamnesia_parser())]


# ---------------------------------------------------------------- MCP
def _mcp_tools(env_extra: dict[str, str]) -> list[dict]:
    env = {**os.environ, **env_extra, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-c", _MCP_PROBE], cwd=ROOT, env=env, capture_output=True,
                       text=True, encoding="utf-8", timeout=120)
    for line in r.stdout.splitlines():
        if line.startswith("@@JSON@@"):
            return json.loads(line[len("@@JSON@@"):])
    raise RuntimeError(f"falha ao listar tools MCP: {r.stderr[-500:]}")


def _sig(schema: dict) -> str:
    req = set(schema.get("required", []))
    parts = []
    for n, p in (schema.get("properties") or {}).items():
        t = p.get("type") or "/".join(x.get("type", "?") for x in p.get("anyOf", [])) or "any"
        if "enum" in p:
            t = "|".join(map(str, p["enum"]))
        parts.append(f"{n}{'' if n in req else '?'}: {t}")
    return ", ".join(parts)


def mcp_section() -> list[str]:
    out = ["## MCP (servidor `memory-gateway`, stdio)", "",
           "Fonte: `server.list_tools()` de `app/mcp/server.py` em subprocesso, uma vez por variante.", ""]
    base: set[str] = set()
    for i, (label, env) in enumerate(MCP_VARIANTS):
        tools = _mcp_tools(env)
        names = {t["name"] for t in tools}
        out += [f"### Tools — {label}: {len(tools)}", "",
                "| Tool | Parâmetros | Descrição |", "| --- | --- | --- |"]
        for t in sorted(tools, key=lambda x: x["name"]):
            if i and t["name"] in base:
                continue  # só mostra o que a variante ACRESCENTA
            first = (t["description"].strip().splitlines() or [""])[0]
            out.append(f"| `{t['name']}` | `{_md(_sig(t['schema']))}` | {_md(first)} |")
        if i:
            out.append(f"\n(+ as {len(base)} tools do conjunto padrão.)")
        else:
            base = names
        out.append("")
    return out


def render() -> str:
    head = [
        "<!-- GERADO por scripts/gen_interface_docs.py (ANA-063). NÃO edite à mão: rode o script. -->",
        "<!-- tests/test_docs_interfaces.py falha se este arquivo divergir do código. -->",
        "",
        "# Interfaces do Anamnésia / Memory Gateway (geradas do código)",
        "",
        "Contrato único de REST, CLI e MCP. Contexto e semântica: [README](../README.md) · "
        "[MEMORY_SEARCH_MODES](guides/MEMORY_SEARCH_MODES.md) · [SECURITY](guides/SECURITY.md).",
        "",
    ]
    return "\n".join([*head, *rest_section(), *cli_sections(), *mcp_section()]).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 se docs/INTERFACES.md estiver desatualizado")
    ns = ap.parse_args(argv)
    text = render()
    if ns.check:
        cur = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if cur != text:
            print("docs/INTERFACES.md desatualizado: rode scripts/gen_interface_docs.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"escrito {OUT.relative_to(ROOT)} ({text.count(chr(10))} linhas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Gera a referência de variáveis de ambiente (ANA-073) a partir do código.

Varre via AST os módulos Python (app/, config/, anamnesia/, memory_gateway/) procurando leituras
de variáveis de ambiente (os.environ[...], os.environ.get/pop/setdefault, os.getenv e os helpers
env_str/env_int/env_float/env_bool/_env_int) e escreve ``docs/ENVIRONMENT_REFERENCE.md``.

    python scripts/gen_config_reference.py            # reescreve o arquivo
    python scripts/gen_config_reference.py --check    # exit 1 se estiver desatualizado

Usado por ``tests/test_docs_env.py``: toda variável lida pelo código precisa estar na tabela
(e o arquivo precisa estar fresco).
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("app", "config", "anamnesia", "memory_gateway")
OUT = ROOT / "docs" / "ENVIRONMENT_REFERENCE.md"
ENV_HELPERS = {"env_str", "env_int", "env_float", "env_bool", "_env_int", "_env_bool", "_env_float",
               "_env_str", "_url", "getenv"}
ENV_METHODS = {"get", "pop", "setdefault"}
ENV_OBJECTS = {"environ", "env"}
_MIN_LEN = 3

# Tipos: user (o usuário define), interna (escrita/derivada pelo Gateway), sistema (do SO/git).
INTERNAL = {
    "MG_LOCAL_TOKEN": "gerada no primeiro start e gravada no .env; não defina à mão",
    "MG_AGENT_ROLE": "exportada pelo Gateway para o PTY do subagente",
    "MG_MCP_CONFIG": "exportada pelo Gateway para o PTY (fallback MCP)",
    "MG_MCP_COMMAND": "exportada pelo Gateway para o PTY (fallback MCP)",
    "MG_MCP_ARGS": "exportada pelo Gateway para o PTY (fallback MCP)",
    "MG_MCP_URL": "exportada pelo Gateway para o PTY (fallback MCP)",
    "MG_TERMINAL_SESSION": "id da sessão de terminal, exportado pelo Gateway ao PTY",
    "MEMORY_GATEWAY_URL": "URL do Gateway injetada pelo Gateway no MCP/PTY do agente",
    "ANAMNESIA_ROLE": "papel do passo, exportado pelo orquestrador ao subagente",
    "ANAMNESIA_STEP": "id do passo, exportado pelo orquestrador",
    "ANAMNESIA_STEP_DIR": "diretório do passo, exportado pelo orquestrador",
    "ANAMNESIA_MODEL_ID": "id do modelo do passo, exportado pelo orquestrador",
    "ANAMNESIA_MODEL": "modelo do passo, exportado pelo orquestrador",
}
SYSTEM = {
    "LOCALAPPDATA": "diretório de dados do Windows (base do diretório do usuário)",
    "GIT_OPTIONAL_LOCKS": "definida pelo Gateway ao chamar git",
    "GIT_TERMINAL_PROMPT": "definida pelo Gateway ao chamar git",
    "PYTHONIOENCODING": "definida pelo Gateway ao lançar subprocessos (UTF-8)",
    "PYTHONUTF8": "definida pelo Gateway ao lançar subprocessos (UTF-8)",
    "PYTEST_CURRENT_TEST": "definida pelo pytest; o Gateway só a lê para recusar rede real em testes",
    "SHELL": "shell do usuário (Unix), usado para escolher o shell dos terminais",
    "XDG_DATA_HOME": "base XDG do diretório de dados no Linux",
}


def env_example_comments(root: Path = ROOT) -> dict[str, str]:
    """NOME -> primeira linha do bloco de comentário logo acima de `NOME=` ou `# NOME=`."""
    p = root / ".env.example"
    out: dict[str, str] = {}
    if not p.exists():
        return out
    block: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = re.match(r"#?\s*([A-Z][A-Z0-9_]{2,})=", line)
        if m:
            out.setdefault(m.group(1), block[0] if block else "")
            block = []
        elif line.startswith("#") and not line.startswith("# ---"):
            block.append(line.lstrip("# ").strip())
        else:
            block = []
    return out


def _const(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        v = node.value
        if len(v) >= _MIN_LEN and v.upper() == v and v[0].isalpha() and v.replace("_", "").isalnum():
            return v
    return None


def _is_env_obj(node: ast.AST) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in ENV_OBJECTS
    return isinstance(node, ast.Name) and node.id in ENV_OBJECTS


def _call_name(func: ast.AST) -> tuple[str | None, bool]:
    """(nome, é_método_de_env)"""
    if isinstance(func, ast.Name):
        return func.id, False
    if isinstance(func, ast.Attribute):
        return func.attr, _is_env_obj(func.value)
    return None, False


def scan_file(path: Path, rel: str, found: dict[str, dict]) -> None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return

    # Constantes de módulo `NOME = "VAR"` usadas como argumento (ex.: HOME_ENV_VAR).
    consts = {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
              and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
              for t in n.targets if isinstance(t, ast.Name)}

    def arg_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name) and node.id in consts:
            return _const(ast.Constant(consts[node.id]))
        return _const(node)

    def add(name: str, default: str | None) -> None:
        d = found.setdefault(name, {"files": set(), "defaults": set()})
        d["files"].add(rel)
        if default is not None:
            d["defaults"].add(default)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            name, on_env = _call_name(node.func)
            first = arg_name(node.args[0])
            if first and name and ((on_env and name in ENV_METHODS) or name in ENV_HELPERS):
                default = None
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    default = repr(node.args[1].value)
                add(first, default)
        elif isinstance(node, ast.Subscript) and _is_env_obj(node.value):
            c = arg_name(node.slice)
            if c:
                add(c, None)
        elif isinstance(node, ast.Compare):
            if isinstance(node.ops[0], (ast.In, ast.NotIn)) and _is_env_obj(node.comparators[0]):
                c = arg_name(node.left)
                if c:
                    add(c, None)


def collect(root: Path = ROOT) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            scan_file(p, p.relative_to(root).as_posix(), found)
    return found


def kind_of(name: str) -> str:
    return "interna" if name in INTERNAL else "sistema" if name in SYSTEM else "user"


def _group(name: str) -> str:
    if name.startswith(("JEV_", "TYPESAFE_")):
        return "JEV / TypeSafe"
    if name.startswith("ANAMNESIA_"):
        return "ANAMNESIA_*"
    if name.startswith("MG_"):
        return "MG_*"
    return "Outras"


def render(found: dict[str, dict], comments: dict[str, str] | None = None) -> str:
    comments = env_example_comments() if comments is None else comments
    lines = [
        "<!-- GERADO por scripts/gen_config_reference.py (ANA-073). NÃO edite à mão: rode o script. -->",
        "<!-- tests/test_docs_env.py falha se esta tabela divergir do código. -->",
        "",
        "# Referência de variáveis de ambiente (gerada)",
        "",
        f"{len(found)} variáveis lidas pelo código (`app/`, `config/`, `anamnesia/`, `memory_gateway/`).",
        "Hierarquia de precedência: [CONFIGURATION.md](guides/CONFIGURATION.md). "
        "Modelo comentado para copiar: [`.env.example`](../.env.example).",
        "",
        "**Tipo**: `user` = você define; `interna` = escrita/derivada pelo próprio Gateway; "
        "`sistema` = do SO/git.",
        "",
    ]
    groups: dict[str, list[str]] = {}
    for n in sorted(found):
        groups.setdefault(_group(n), []).append(n)
    for g in sorted(groups):
        lines += [f"## {g}", "", "| Variável | Tipo | Default no código | Descrição | Lida em |",
                  "| --- | --- | --- | --- | --- |"]
        for n in groups[g]:
            d = found[n]
            defaults = ", ".join(f"`{x}`" for x in sorted(d["defaults"])).replace("|", "\\|") or "—"
            where = ", ".join(f"`{f}`" for f in sorted(d["files"]))
            desc = (INTERNAL.get(n) or SYSTEM.get(n) or comments.get(n) or "—").replace("|", "\\|")
            lines.append(f"| `{n}` | {kind_of(n)} | {defaults} | {desc} | {where} |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 se docs/ENVIRONMENT_REFERENCE.md estiver desatualizado")
    ns = ap.parse_args(argv)
    text = render(collect())
    if ns.check:
        cur = OUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUT.exists() else ""
        if cur != text:
            print("docs/ENVIRONMENT_REFERENCE.md desatualizado: rode scripts/gen_config_reference.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"escrito {OUT.relative_to(ROOT)} ({text.count(chr(10))} linhas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

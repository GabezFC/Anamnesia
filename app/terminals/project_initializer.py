"""Inicializador de projeto: instala no projeto selecionado os arquivos que o ligam ao Anamnésia/Memory Gateway.

Fonte única: `config/project_manifest.json` (quais diretórios/arquivos) + `config/project_templates/*.tmpl`
(conteúdo). Os valores dinâmicos (vault, URL do gateway, servidor MCP) vêm da configuração viva do Memory Gateway
(`MEMORY_GATEWAY_VAULT` / `config.retrieval.resolve_vault_path`, `app.terminals.mcp_inject.server_spec`), nunca de
caminhos fixos no código.

Dois destinos: o projeto selecionado e a RAIZ do vault configurado (AGENTS.md, CLAUDE.md, HOME.md, .base — seção
"vault" do manifesto). No vault só entram esses arquivos-guia, e só se ausentes; nada existente é tocado e o vault
nunca é copiado para o projeto.

Segurança (mesmas garantias de `memory_store/vault_scaffold.py`): só cria o que falta, modo 'x' (nunca sobrescreve),
nunca apaga/move/edita, não segue link simbólico/junction, não sai da raiz do projeto, não toca no vault.
Idempotente: o que já existe é relatado como `existing` e não é lido nem alterado. Sem Hermes, sem subprocesso.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from config.paths import PACKAGE_ROOT

MANIFEST_PATH = PACKAGE_ROOT / "config" / "project_manifest.json"
TEMPLATES_DIR = PACKAGE_ROOT / "config" / "project_templates"
_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


class InitError(Exception):
    """Falha que impede a operação inteira. `code` é legível por máquina."""

    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code, self.message, self.hint = code, message, hint


@dataclass(frozen=True)
class Requirement:
    kind: str                 # 'dir' | 'file'
    path: str                 # relativo à raiz do escopo, separador '/'
    scope: str = "project"    # 'project' | 'vault' (raiz onde o item é criado)
    description: str = ""
    template: str = ""
    required: bool = True


@dataclass
class Report:
    project: str
    root: str
    dry_run: bool = False
    created: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)   # {path, reason}

    @property
    def already_configured(self) -> bool:
        return not self.created and not self.failed

    @property
    def ok(self) -> bool:
        return not self.failed

    def to_dict(self) -> dict:
        return {"project": self.project, "root": self.root, "dry_run": self.dry_run, "created": self.created,
                "existing": self.existing, "failed": self.failed, "ok": self.ok,
                "already_configured": self.already_configured}


# ---------------------------------------------------------------- Memory Gateway configuration
def load_memory_gateway_config(environ=None) -> dict:
    """Valores vivos do Memory Gateway usados nos templates.

    Falha com `gateway_not_configured` se nenhum vault foi configurado (nada de cair no corpus de exemplo
    em silêncio) ou se o configurado não existe.
    """
    from app.terminals import mcp_inject
    from config.retrieval import LEGACY_VAULT_ENV_VAR, VAULT_ENV_VAR, resolve_vault_path
    env = os.environ if environ is None else environ
    raw = (env.get(VAULT_ENV_VAR) or env.get(LEGACY_VAULT_ENV_VAR) or "").strip()
    hint = "Defina o vault em Anamnésia > Configuração > Gateway de Memória, clique em Salvar e tente de novo."
    if not raw:
        raise InitError("gateway_not_configured", "O Memory Gateway ainda não tem um vault configurado (nenhum caminho salvo).", hint)
    vault = resolve_vault_path(raw)
    if not vault.is_dir():
        raise InitError("gateway_not_configured", f"A pasta do vault configurado não existe ou não é uma pasta: {vault}", hint)
    return {"vault_env": VAULT_ENV_VAR, "vault_path": str(vault),
            "gateway_url": env.get("MEMORY_GATEWAY_URL") or mcp_inject.DEFAULT_URL,
            "mcp_server_name": mcp_inject.SERVER_NAME}


# ---------------------------------------------------------------- manifest
def _safe_rel(rel: str) -> str:
    norm = rel.replace("\\", "/").strip()
    parts = norm.split("/")
    if (not norm or norm.startswith("/") or re.match(r"^[A-Za-z]:", norm)
            or any(x in ("", ".", "..") for x in parts)):
        raise InitError("manifest_invalid", f"Caminho inválido no manifesto: {rel!r}")
    return norm


def load_manifest(path: Path | None = None) -> list[Requirement]:
    p = Path(path) if path else MANIFEST_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise InitError("manifest_invalid", f"O manifesto de instalação ({p.name}) está ausente ou inválido: {e}",
                        "Reinstale/atualize o Anamnésia: o arquivo config/project_manifest.json faz parte dele.") from e
    reqs: list[Requirement] = []
    seen: set[tuple[str, str]] = set()
    sections = (("project", data), ("vault", data.get("vault") or {}))
    for scope, sec in sections:
        for kind, key in (("dir", "directories"), ("file", "files")):
            for item in sec.get(key, []):
                rel = _safe_rel(str(item.get("path", "")))
                if (scope, rel.lower()) in seen:
                    raise InitError("manifest_invalid", f"Caminho duplicado no manifesto: {rel}")
                seen.add((scope, rel.lower()))
                if kind == "file" and not item.get("template"):
                    raise InitError("manifest_invalid", f"Arquivo sem template no manifesto: {rel}")
                reqs.append(Requirement(kind, rel, scope, str(item.get("description", "")),
                                        str(item.get("template", "")), bool(item.get("required", True))))
    return reqs


def render_template(name: str, values: dict, templates_dir: Path | None = None) -> str:
    """Substitui `{{chave}}`; `{{chave_json}}` insere o valor como literal JSON.

    Chave desconhecida é erro: nada inválido é gerado em silêncio.
    """
    base = Path(templates_dir) if templates_dir else TEMPLATES_DIR
    if "/" in name or "\\" in name or name.startswith("."):
        raise InitError("manifest_invalid", f"Nome de template inválido: {name!r}")
    try:
        text = (base / name).read_text(encoding="utf-8")
    except OSError as e:
        raise InitError("manifest_invalid", f"Template de instalação ausente: {name}",
                        "Reinstale/atualize o Anamnésia: config/project_templates/ faz parte dele.") from e

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in values and isinstance(values[key], str):
            return values[key]
        if key.endswith("_json") and key[:-5] in values:
            return json.dumps(values[key[:-5]], ensure_ascii=False)
        raise InitError("manifest_invalid", f"Placeholder desconhecido {{{{{key}}}}} em {name}")
    return _PLACEHOLDER.sub(sub, text)


# ---------------------------------------------------------------- project
def resolve_project(path: str | Path) -> Path:
    try:
        root = Path(path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as e:
        raise InitError("project_invalid", f"A pasta do projeto não existe mais: {path}",
                        "Confira se ela foi movida/apagada/está num drive desconectado; remova e registre o projeto de novo.") from e
    if not root.is_dir():
        raise InitError("project_invalid", f"O caminho do projeto não é uma pasta: {root}",
                        "Registre a pasta do projeto, não um arquivo.")
    if not os.access(root, os.W_OK | os.X_OK):
        raise InitError("project_not_writable", f"Permissão de escrita negada na pasta do projeto: {root}",
                        "Ajuste as permissões da pasta (ou rode o Anamnésia com acesso a ela) e tente de novo.")
    return root


def _is_link(p: Path) -> bool:
    try:
        return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
    except OSError:
        return True


def _check_path(root: Path, rel: str) -> Path:
    """Alvo dentro da raiz e sem link/junction em nenhum componente (levanta PermissionError)."""
    cur = root
    for part in rel.split("/"):
        cur = cur / part
        if os.path.lexists(cur) and _is_link(cur):
            raise PermissionError(f"link simbólico/junction não permitido: {rel}")
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise PermissionError(f"caminho fora do projeto: {rel}")
    return root / rel


def explain_os_error(e: OSError) -> str:
    """Motivo legível (PT-BR) de uma falha de E/S, com o detalhe técnico entre parênteses."""
    import errno
    tech = e.strerror or str(e)
    if isinstance(e, PermissionError) or e.errno in (errno.EACCES, errno.EPERM):
        why = "Permissão de escrita negada nesta pasta (somente leitura, protegida ou arquivo em uso)."
    elif e.errno == errno.EROFS:
        why = "O local é somente leitura."
    elif e.errno == errno.ENOSPC:
        why = "Sem espaço em disco."
    elif e.errno == errno.ENAMETOOLONG:
        why = "Caminho longo demais para o sistema de arquivos."
    elif isinstance(e, FileNotFoundError):
        why = "O diretório do projeto deixou de existir durante a operação."
    elif isinstance(e, (FileExistsError, NotADirectoryError, IsADirectoryError)):
        why = "Já existe um item de tipo diferente nesse caminho (não foi alterado)."
    else:
        why = "Erro do sistema de arquivos."
    return f"{why} ({tech})" if tech and tech not in why else why


VAULT_PREFIX = "vault:"


def display_path(r: Requirement) -> str:
    """Nome mostrado no relatório; itens do vault levam o prefixo `vault:`."""
    return (VAULT_PREFIX if r.scope == "vault" else "") + r.path


def inspect_existing(root: Path, reqs: list[Requirement]) -> dict[str, bool]:
    """{path: já existe?}. `lexists`: um link quebrado também conta como existente (nunca é substituído)."""
    return {r.path: os.path.lexists(root / r.path) for r in reqs}


def initialize(project_root: str | Path, project_name: str = "", *, dry_run: bool = False, environ=None,
               manifest_path: Path | None = None, templates_dir: Path | None = None) -> Report:
    """Fluxo completo. Lança `InitError` só para falhas globais; falha por arquivo vai em `report.failed`."""
    from app.terminals import mcp_inject
    root = resolve_project(project_root)
    cfg = load_memory_gateway_config(environ)
    reqs = load_manifest(manifest_path)
    name = project_name or root.name
    values: dict = {"project_name": name, **cfg,
                    "mcp_server": mcp_inject.server_spec(name, None, cfg["gateway_url"], environ)}
    # Renderiza tudo antes de tocar no disco: um template quebrado aborta sem criar nada pela metade.
    rendered = {(r.scope, r.path): render_template(r.template, values, templates_dir)
                for r in reqs if r.kind == "file"}
    roots = {"project": root, "vault": Path(cfg["vault_path"])}
    exists = {s: inspect_existing(roots[s], [r for r in reqs if r.scope == s]) for s in roots}
    rep = Report(project=name, root=str(root), dry_run=dry_run)
    for r in reqs:
        shown = display_path(r)
        base = roots[r.scope]
        try:
            if r.scope == "vault" and not os.access(base, os.W_OK | os.X_OK):
                raise PermissionError(13, "Permission denied")
            target = _check_path(base, r.path)
            if exists[r.scope][r.path]:
                if (r.kind == "dir") != target.is_dir():
                    raise IsADirectoryError(0, "já existe com tipo diferente do esperado")
                rep.existing.append(shown)
                continue
            if not dry_run:
                if r.kind == "dir":
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        with open(target, "x", encoding="utf-8", newline="\n") as fh:  # 'x': nunca sobrescreve
                            fh.write(rendered[(r.scope, r.path)])
                    except FileExistsError:  # corrida: criado por outro processo entre inspeção e escrita
                        rep.existing.append(shown)
                        continue
            rep.created.append(shown)
        except OSError as e:
            reason = explain_os_error(e)
            if r.scope == "vault":
                reason = f"Vault ({base}): {reason}"
            rep.failed.append({"path": shown, "reason": reason})
    return rep

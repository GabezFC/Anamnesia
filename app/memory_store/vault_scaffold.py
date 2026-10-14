"""Vault scaffold: creates the standard Anamnesia memory folder layout (and the three note templates) inside a vault.

Safe by construction: only creates missing folders/files, NEVER overwrites or deletes anything, stays inside the
given root (no '..', no symlink/junction targets outside), and supports a dry run that lists what would be created.
"""
from __future__ import annotations

from pathlib import Path

FOLDERS: tuple[str, ...] = (
    "00-Inbox", "10-Trabalho", "20-Dev-IA", "30-Projetos", "40-Estudos",
    "50-Pessoal/perfil", "50-Pessoal/preferencias", "70-Daily", "99-Templates",
)
PROJECT_SUBFOLDERS: tuple[str, ...] = ("Notes/Notas", "Notes/Decisões", "Notes/Daily", "arquitetura")

TEMPLATES: dict[str, str] = {
    '_nota': '---\nid: {{date:YYYYMMDD-HHmm}}\ntitle: {{title}}\narea: Inbox\ntype: nota\nprojeto:\ntags: []\nstatus: inbox\ncreated: {{date:YYYY-MM-DD HH:mm}}\nupdated: {{date:YYYY-MM-DD HH:mm}}\n---\n\n# {{title}}\n\n## Resumo\n<!-- O conceito em 1–3 frases. Se não couber aqui, a nota tem mais de um conceito: divida. -->\n\n## Conteúdo\n<!-- O desenvolvimento. Bullets > parágrafos. -->\n\n## Relacionadas\n- [[ ]]\n\n## Próximo passo\n- [ ] \n',
    '_decisao': '---\nid: {{date:YYYYMMDD-HHmm}}\ntitle: {{title}}\narea: Projetos\ntype: decisao\nprojeto:\ntags: [decisao]\nstatus: ativo\ncreated: {{date:YYYY-MM-DD HH:mm}}\nupdated: {{date:YYYY-MM-DD HH:mm}}\n---\n\n# {{title}}\n\n## Contexto\n<!-- Qual era a situação que forçou a decisão. -->\n\n## Decisão\n<!-- O que foi decidido, em uma frase afirmativa e no passado. -->\n\n## Alternativas consideradas\n| Opção | A favor | Contra | Descartada porque |\n| --- | --- | --- | --- |\n|  |  |  |  |\n\n## Consequências\n<!-- O que essa decisão passa a exigir, custar ou impedir. -->\n\n## Revisar quando\n<!-- O gatilho que reabre a decisão. Data, métrica ou evento. -->\n\n## Relacionadas\n- [[ ]]\n',
    '_daily': '---\nid: {{date:YYYYMMDD-HHmm}}\ntitle: {{date:YYYY-MM-DD}}\narea: Daily\ntype: daily\ntags: [daily]\nstatus: ativo\ncreated: {{date:YYYY-MM-DD HH:mm}}\nupdated: {{date:YYYY-MM-DD HH:mm}}\n---\n\n# {{date:YYYY-MM-DD}}\n\n## Foco do dia\n<!-- A única coisa que, se sair, faz o dia valer. -->\n\n## Feito\n- \n\n## Aberto\n- [ ] \n\n## Notas do dia\n<!-- Captura solta. O que virar conceito próprio sai daqui e vira nota atômica. -->\n\n## Links\n- [[ ]]\n',
}


def _is_link(p: Path) -> bool:
    try:
        return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
    except OSError:
        return True


def plan(root: Path) -> list[dict]:
    """Return [{'kind': 'dir'|'file', 'path': rel, 'exists': bool}] in creation order."""
    items: list[dict] = []
    for rel in FOLDERS:
        items.append({"kind": "dir", "path": rel, "exists": (root / rel).is_dir()})
    for name in TEMPLATES:
        rel = f"99-Templates/{name}.md"
        items.append({"kind": "file", "path": rel, "exists": (root / rel).exists()})
    return items


def scaffold(root: str | Path, *, dry_run: bool = False) -> dict:
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"vault inexistente: {root}")
    created: list[str] = []
    skipped: list[str] = []
    for it in plan(root):
        target = (root / it["path"]).resolve()
        if root != target and root not in target.parents:
            raise PermissionError(f"caminho fora do vault: {it['path']}")
        # every existing ancestor below root must not be a link that could redirect the write
        cur = root
        for part in Path(it["path"]).parts:
            cur = cur / part
            if cur.exists() and _is_link(cur):
                raise PermissionError(f"link simbólico/junction não permitido: {it['path']}")
        if it["exists"]:
            skipped.append(it["path"])
            continue
        if not dry_run:
            if it["kind"] == "dir":
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "x", encoding="utf-8", newline="") as fh:   # 'x': never overwrite
                    fh.write(TEMPLATES[Path(it["path"]).stem])
        created.append(it["path"])
    return {"root": str(root), "dry_run": dry_run, "created": created, "skipped": skipped}


def scaffold_project(root: str | Path, project: str, *, dry_run: bool = False) -> dict:
    """30-Projetos/<project>/{Notes/Notas,Notes/Decisões,Notes/Daily,arquitetura} (same safety rules)."""
    name = project.strip()
    if not name or any(c in name for c in r'\/:*?"<>|') or name in {".", ".."}:
        raise ValueError("nome de projeto inválido")
    root = Path(root).resolve()
    created = []
    for sub in PROJECT_SUBFOLDERS:
        d = root / "30-Projetos" / name / sub
        if not d.is_dir():
            if not dry_run:
                d.mkdir(parents=True, exist_ok=True)
            created.append(f"30-Projetos/{name}/{sub}")
    return {"root": str(root), "dry_run": dry_run, "created": created}

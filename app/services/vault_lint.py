"""Deterministic, READ-ONLY lint of an Obsidian vault (proposta item 0.3).

The vault follows a documented convention: frontmatter in every note, `area` mirroring the
first-level folder, `projeto:` mandatory under `30-Projetos/`, kebab-case filenames, wikilinks
that resolve by filename. This module checks that convention with zero LLM cost and zero writes:
files are only ever opened for reading, through `ObsidianVault`, the single module allowed to
touch the vault (§8).

Determinism: the same vault always produces the same report. Findings are sorted by
(category order, path, detail) and every rule is a pure function of the file bytes.

Design notes
------------
* The convention is data, not code: the folder -> `area` map and the root/template/daily
  exceptions are module-level constants, so a vault with a different layout is simply not
  checked on the rules it does not have, instead of producing false positives.
* A note with no frontmatter at all is reported ONCE (as `sem_frontmatter`) and the per-field
  rules are skipped for it, otherwise 4 notes without frontmatter would explode into 36 findings
  and bury the real ones.
* A root `.md` outside the three allowed ones is reported once
  (`md_fora_do_padrao_na_raiz`) and excluded from every note-level rule, for the same reason.
* Wikilinks resolve by filename without extension (Obsidian's own rule), accepting
  `[[x|alias]]`, `[[x#anchor]]` and `[[x#anchor|alias]]`. A path-shaped target (`[[pasta/x]]`)
  is accepted too. Links inside fenced code blocks are ignored, as are the intentional
  `[[assim]]` / `[[]]` examples and everything inside `99-Templates/` (the templates document
  the syntax, they do not use it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.obsidian import ObsidianVault, split_frontmatter

# -- convention (data) --------------------------------------------------------------------------

#: first-level folder -> the value `area:` must have for a note living there.
AREA_BY_FOLDER: dict[str, str] = {
    "00-Inbox": "Inbox",
    "10-Trabalho": "Trabalho",
    "20-Dev-IA": "Dev-IA",
    "30-Projetos": "Projetos",
    "40-Estudos": "Estudos",
    "50-Pessoal": "Pessoal",
    "70-Daily": "Daily",
}

#: folders where `projeto:` is mandatory (§7.5).
PROJECT_FOLDERS: tuple[str, ...] = ("30-Projetos",)

#: the only `.md` files allowed at the vault root (§3.7).
ROOT_NOTES_ALLOWED: tuple[str, ...] = ("AGENTS.md", "CLAUDE.md", "HOME.md")

#: folder whose notes are templates (`_*` names); excluded from the note-level rules.
TEMPLATES_FOLDER = "99-Templates"

#: folder whose notes are named by date instead of by subject (§3.2 exception).
DAILY_FOLDER = "70-Daily"

#: frontmatter keys every note must carry (§4).
REQUIRED_FIELDS: tuple[str, ...] = (
    "id", "title", "area", "type", "tags", "status", "created", "updated",
)

#: `id` is an immutable creation stamp (§4).
ID_PATTERN = re.compile(r"^\d{8}-\d{4}$")

#: `created` / `updated` are `YYYY-MM-DD HH:MM` (§4).
DATETIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

#: §3.2: lowercase, hyphen instead of space, no accent, no underscore.
KEBAB_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: `_nota.md` in `99-Templates/` (§3.2 exception).
TEMPLATE_NAME_PATTERN = re.compile(r"^_[a-z0-9]+(?:-[a-z0-9]+)*$")

#: `2026-09-19.md` in `70-Daily/` (§3.2 exception).
DAILY_NAME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: `[[alvo]]`, `[[alvo|alias]]`, `[[alvo#ancora]]`, `[[alvo#ancora|alias]]`.
WIKILINK_PATTERN = re.compile(r"\[\[([^\[\]]*?)\]\]")

#: Placeholders that document the syntax instead of using it: `[[assim]]` in AGENTS.md/CLAUDE.md
#: and `[[]]` in the templates are intentional, never a broken link.
INTENTIONALLY_EMPTY_LINKS: frozenset[str] = frozenset({"", "assim"})

#: A note longer than this is a candidate for splitting (1 note = 1 concept, §3.1).
MAX_NOTE_CHARS = 20_000

#: Categories, in report order. The key is the stable JSON contract; the label is prose.
CATEGORIES: tuple[tuple[str, str], ...] = (
    ("sem_frontmatter", "sem frontmatter"),
    ("campos_faltando", "campos obrigatorios faltando"),
    ("area_incorreta", "area diferente da pasta de 1o nivel"),
    ("projeto_ausente", "projeto: ausente em pasta de projeto"),
    ("data_invalida", "id/created/updated fora do formato"),
    ("nome_fora_do_padrao", "nome fora do padrao"),
    ("wikilink_sem_alvo", "wikilink sem alvo"),
    ("nomes_duplicados", "nomes duplicados"),
    ("orfa", "nota orfa (sem link de entrada)"),
    ("nota_grande", "nota maior que o limite"),
    ("arquivo_nao_md_raiz", "arquivo nao-.md solto na raiz"),
    ("md_fora_do_padrao_na_raiz", ".md na raiz fora dos 3 permitidos"),
)

CATEGORY_ORDER: dict[str, int] = {key: i for i, (key, _) in enumerate(CATEGORIES)}
CATEGORY_LABELS: dict[str, str] = dict(CATEGORIES)

_FM_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
_FM_LIST_ITEM = re.compile(r"^\s+-\s")


# -- report -------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    """One rule violation. `detail` says what is wrong, in a form an agent can act on."""

    category: str
    path: str
    detail: str

    def to_dict(self) -> dict:
        return {"category": self.category, "path": self.path, "detail": self.detail}


@dataclass
class LintReport:
    """Result of one lint run."""

    vault: str
    files: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.findings)

    def by_category(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = {}
        for f in self.findings:
            out.setdefault(f.category, []).append(f)
        return out

    def counts(self) -> dict[str, int]:
        """Item count per category, in report order (zero-count categories included)."""
        grouped = self.by_category()
        return {key: len(grouped.get(key, ())) for key, _ in CATEGORIES}

    def to_dict(self) -> dict:
        return {
            "vault": self.vault,
            "files": self.files,
            "total": self.total,
            "counts": self.counts(),
            "findings": [f.to_dict() for f in self.findings],
        }

    def render(self) -> str:
        """Human-readable report, grouped by category. Stable output for a given vault."""
        lines = [f"vault: {self.vault}", f"arquivos .md: {self.files}", f"itens: {self.total}"]
        grouped = self.by_category()
        for key, label in CATEGORIES:
            items = grouped.get(key)
            if not items:
                continue
            lines.append("")
            lines.append(f"[{key}] {label} ({len(items)})")
            lines.extend(f"  - {f.path}: {f.detail}" for f in items)
        if not self.findings:
            lines.append("")
            lines.append("OK: nenhum item.")
        return "\n".join(lines)


# -- vault shape --------------------------------------------------------------------------------

@dataclass
class VaultNote:
    """One markdown file, with the parse products the rules need."""

    path: str
    text: str
    frontmatter: dict[str, str] | None  # None = no frontmatter block at all
    stem: str
    folder: str  # "" for files at the vault root

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def first_folder(self) -> str:
        return self.folder.split("/", 1)[0] if self.folder else ""

    @property
    def is_root(self) -> bool:
        return not self.folder

    @property
    def is_template(self) -> bool:
        return self.first_folder == TEMPLATES_FOLDER

    @property
    def is_daily(self) -> bool:
        return self.first_folder == DAILY_FOLDER


def _parse_frontmatter_fields(block: str) -> dict[str, str]:
    """Top-level `key: value` pairs of a frontmatter block.

    Deliberately minimal: the vault convention only uses scalars and block lists, and a real
    YAML parser is not needed to answer "is this key present and what is its scalar value".
    List values (`tags:` followed by `- item` lines) are recorded as the empty string, which
    still counts as present.
    """
    out: dict[str, str] = {}
    for line in block.splitlines()[1:-1]:  # drop the `---` fences
        m = _FM_KEY.match(line)
        if not m:
            continue
        value = m.group(2).strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out.setdefault(m.group(1).strip().lower(), value)
    return out


def _is_fenced(line: str) -> bool:
    s = line.lstrip()
    return s.startswith("```") or s.startswith("~~~")


def strip_code_fences(text: str) -> str:
    """Blank out fenced code blocks, keeping line count (so line numbers stay usable)."""
    out, in_fence = [], False
    for line in text.split("\n"):
        if _is_fenced(line):
            in_fence = not in_fence
            out.append("")
        else:
            out.append("" if in_fence else line)
    return "\n".join(out)


def _valid_stem(note: VaultNote) -> bool:
    """§3.2 kebab-case, with the template and daily exceptions."""
    stem = note.stem
    if note.is_template:
        return bool(TEMPLATE_NAME_PATTERN.match(stem))
    if note.is_daily:
        return bool(DAILY_NAME_PATTERN.match(stem) or KEBAB_PATTERN.match(stem))
    if note.is_root and note.name in ROOT_NOTES_ALLOWED:
        return True
    return bool(KEBAB_PATTERN.match(stem))


# -- rules --------------------------------------------------------------------------------------

def _check_frontmatter(notes: list[VaultNote]) -> list[Finding]:
    """`sem_frontmatter`, `campos_faltando`, `area_incorreta`, `projeto_ausente`, `data_invalida`."""
    out: list[Finding] = []
    for n in notes:
        if n.is_template or n.frontmatter is None:
            continue
        fm = n.frontmatter
        missing = [f for f in REQUIRED_FIELDS if f not in fm]
        if missing:
            out.append(Finding("campos_faltando", n.path, "faltam: " + ", ".join(missing)))

        expected_area = AREA_BY_FOLDER.get(n.first_folder)
        if expected_area and fm.get("area") and fm["area"] != expected_area:
            out.append(Finding("area_incorreta", n.path,
                               f"area: {fm['area']!r} mas a pasta {n.first_folder}/ exige {expected_area!r}"))

        if n.first_folder in PROJECT_FOLDERS and not fm.get("projeto"):
            out.append(Finding("projeto_ausente", n.path,
                               f"nota em {n.first_folder}/ sem 'projeto:'"))

        if "id" in fm and not ID_PATTERN.match(fm["id"]):
            out.append(Finding("data_invalida", n.path, f"id: {fm['id']!r} fora de YYYYMMDD-HHMM"))
        for key in ("created", "updated"):
            if key in fm and not DATETIME_PATTERN.match(fm[key]):
                out.append(Finding("data_invalida", n.path,
                                   f"{key}: {fm[key]!r} fora de 'YYYY-MM-DD HH:MM'"))
    return out


def _check_names(scannable: list[VaultNote], all_notes: list[VaultNote]) -> list[Finding]:
    """`nome_fora_do_padrao` and `nomes_duplicados` (§3.2: the name resolves the wikilink).

    The name pattern is checked on `scannable` (a stray root `.md` is already reported by the
    root-layout rule, so flagging its name too would only add noise), but duplicates are
    computed over `all_notes` — two files sharing a name is a wikilink ambiguity wherever
    they live.
    """
    out: list[Finding] = []
    for n in scannable:
        if not _valid_stem(n):
            out.append(Finding("nome_fora_do_padrao", n.path,
                               f"'{n.name}' fora do kebab-case minusculo (§3.2)"))
    by_stem: dict[str, list[str]] = {}
    for n in all_notes:
        by_stem.setdefault(n.stem, []).append(n.path)
    for stem, paths in sorted(by_stem.items()):
        if len(paths) > 1:
            out.append(Finding("nomes_duplicados", "; ".join(sorted(paths)),
                               f"'{stem}' aparece em {len(paths)} arquivos: o wikilink fica ambíguo"))
    return out


def _link_target(raw: str) -> str:
    """`pasta/x#ancora|alias` -> `pasta/x`. Returns '' for empty/placeholder links."""
    target = raw.split("|", 1)[0]
    target = target.split("#", 1)[0]
    target = target.strip().strip("/")
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target


def _check_links(notes: list[VaultNote]) -> tuple[list[Finding], set[str]]:
    """`wikilink_sem_alvo`; also returns the set of paths that have at least one incoming link."""
    out: list[Finding] = []
    incoming: set[str] = set()
    by_stem = {n.stem: n.path for n in notes}
    by_path = {n.path[:-3]: n.path for n in notes}
    for n in notes:
        if n.is_template:
            continue
        body = strip_code_fences(n.text)
        for raw in WIKILINK_PATTERN.findall(body):
            if raw.strip() in INTENTIONALLY_EMPTY_LINKS:
                continue
            target = _link_target(raw)
            if not target:
                continue
            dest = by_stem.get(target) or by_path.get(target)
            if dest is None:
                out.append(Finding("wikilink_sem_alvo", n.path, f"[[{raw}]] nao resolve"))
            elif dest != n.path:
                incoming.add(dest)
    return out, incoming


def _check_orphans(notes: list[VaultNote], incoming: set[str]) -> list[Finding]:
    """`orfa`: nobody links to it, so the graph never reaches it.

    Excluded: the three root notes (they are the entry point, not a target), templates (nothing
    links a template) and daily notes (a daily note is reached through the hub by date, and the
    vault's own rule does not require inbound links there).
    """
    out: list[Finding] = []
    for n in notes:
        if n.is_template or n.is_daily:
            continue
        if n.is_root and n.name in ROOT_NOTES_ALLOWED:
            continue
        if n.path in incoming:
            continue
        out.append(Finding("orfa", n.path, "nenhum wikilink aponta para esta nota"))
    return out


def _check_sizes(notes: list[VaultNote], max_chars: int) -> list[Finding]:
    return [Finding("nota_grande", n.path, f"{len(n.text)} caracteres (limite {max_chars})")
            for n in notes if len(n.text) > max_chars]


def _check_root(vault: ObsidianVault, notes: list[VaultNote]) -> list[Finding]:
    """`arquivo_nao_md_raiz` and `md_fora_do_padrao_na_raiz` (§3.7)."""
    out: list[Finding] = []
    for name in sorted(_list_root_entries(vault)):
        path = name if "/" in name else name
        if not name.endswith(".md"):
            out.append(Finding("arquivo_nao_md_raiz", path,
                               f"'{name}' nao e .md e esta solto na raiz"))
        elif name not in ROOT_NOTES_ALLOWED:
            out.append(Finding("md_fora_do_padrao_na_raiz", path,
                               f"'{name}' nao esta entre os 3 permitidos "
                               f"({', '.join(ROOT_NOTES_ALLOWED)})"))
    return out


def _list_root_entries(vault: ObsidianVault) -> list[str]:
    """Non-hidden files directly at the vault root (read-only, no recursion)."""
    out = []
    for rel in vault.list_all():
        if "/" in rel or rel.startswith("."):
            continue
        out.append(rel)
    return out


# -- entry point --------------------------------------------------------------------------------

def _load_notes(vault: ObsidianVault) -> list[VaultNote]:
    notes: list[VaultNote] = []
    for rel in vault.list_markdown():
        text = vault.read(rel)
        block, _body = split_frontmatter(text)
        folder, _, name = rel.rpartition("/")
        notes.append(VaultNote(
            path=rel,
            text=text,
            frontmatter=_parse_frontmatter_fields(block) if block else None,
            stem=name[:-3],
            folder=folder,
        ))
    return notes


def _sort(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (CATEGORY_ORDER.get(f.category, 99), f.path, f.detail))


def lint(vault_path: str | Path, *, max_note_chars: int = MAX_NOTE_CHARS,
         excluded_dirs: tuple[str, ...] = (".obsidian", ".trash", ".git")) -> LintReport:
    """Run every rule over `vault_path` and return the report. Never writes to the vault.

    The returned report is sorted, so two runs over an unchanged vault are identical — that is
    what makes the lint usable as a before/after gate (proposta 0.3).
    """
    vault = ObsidianVault(Path(vault_path), excluded_dirs)
    notes = _load_notes(vault)
    # A root `.md` outside the three allowed ones is a layout problem, reported once by
    # `_check_root`; it is skipped by every note-level rule so it is not counted twice.
    stray_root = {n.path for n in notes if n.is_root and n.name not in ROOT_NOTES_ALLOWED}
    scannable = [n for n in notes if n.path not in stray_root]

    findings: list[Finding] = []
    findings += [Finding("sem_frontmatter", n.path, "nenhum bloco de frontmatter")
                 for n in scannable if n.frontmatter is None and not n.is_template
                 and not (n.is_root and n.name in ROOT_NOTES_ALLOWED)]
    findings += _check_frontmatter(scannable)
    findings += _check_names(scannable, notes)
    link_findings, incoming = _check_links(notes)
    findings += link_findings
    findings += _check_orphans(scannable, incoming)
    findings += _check_sizes(scannable, max_note_chars)
    findings += _check_root(vault, notes)
    return LintReport(vault=str(vault.root), files=len(notes), findings=_sort(findings))


def render(report: LintReport) -> str:
    """Text report, grouped by category (the CLI default)."""
    return report.render()

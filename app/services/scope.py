"""Generic project/scope discovery and query scoping (§14, §15, §30, §40).

The vault is a flat set of markdown paths. This module derives PROJECT and AREA entities from
those paths plus frontmatter, with NO hardcoded project names anywhere: adding a new project to
the vault makes it appear here automatically, which is the whole requirement (§15).

Discovery rules (data-driven, in order):
  1. frontmatter `projeto: <slug>` is authoritative when present.
  2. otherwise, a note under `<NN-Area>/<Container>/...` belongs to project slug(<Container>)
     ONLY IF that area is a project-bearing area (see PROJECT_AREAS), with the
     `_Cerebro`/`_cerebro` suffix stripped (the vault's own naming convention).
  3. a note directly under `<NN-Area>/` belongs to no project; its scope is the area.

Why PROJECT_AREAS exists: areas like `50-Pessoal/` also have subfolders (`perfil/`,
`preferencias/`) which are plain organisational folders, NOT projects. Treating every
subfolder as a project made them appear as projects in the registry (observed 2026-09-27).
The set is a configurable convention about vault LAYOUT, not a list of project names, so
adding a new project still requires zero code changes (§15, §40).

Scope resolution supports exactly the three searches the architecture requires:
  - one project        scope="projeto:<slug>"
  - several projects    scope="projeto:a,projeto:b"
  - one area            scope="area:<Area>"
  - the whole brain     scope=None / "global"
Cross-contamination is prevented by filtering the candidate pool, never by renaming or moving.

This module is pure and does not touch the vault: it takes the path list the caller already has.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

# `30-Projetos/Norteia_Cerebro/decisoes/x.md` -> area="30-Projetos", container="Norteia_Cerebro"
_AREA_DIR = re.compile(r"^(?P<area>\d{2}-[^/]+)/(?:(?P<container>[^/]+)/)?")
_CEREBRO_SUFFIX = re.compile(r"[_-]?cerebro$", re.I)

GLOBAL_SCOPE = "global"

# Areas whose immediate subfolders are PROJECT containers. A layout convention, not a
# project list: any new folder inside these areas becomes a project automatically.
PROJECT_AREAS = ("30-Projetos",)


def slug(name: str) -> str:
    """Stable, accent-free, lowercase slug. `Norteia_Cerebro` -> `norteia`."""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.replace("_", "-").replace(" ", "-").lower()
    folded = _CEREBRO_SUFFIX.sub("", folded).strip("-")
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9-]", "", folded))


def area_of(rel_path: str) -> str | None:
    m = _AREA_DIR.match(rel_path)
    return m.group("area") if m else None


def container_of(rel_path: str) -> str | None:
    m = _AREA_DIR.match(rel_path)
    return m.group("container") if m else None


def project_of(rel_path: str, frontmatter_projeto: str | None = None,
               project_areas: tuple[str, ...] = PROJECT_AREAS) -> str | None:
    """Project slug a note belongs to, or None if it is area-level / outside the area layout."""
    if frontmatter_projeto:
        s = slug(frontmatter_projeto)
        if s:
            return s
    if area_of(rel_path) not in project_areas:
        return None
    container = container_of(rel_path)
    if not container:
        return None
    # A container that is itself a note (`foo.md`) is not a project directory.
    if container.lower().endswith(".md"):
        return None
    return slug(container) or None


@dataclass
class Project:
    """A project entity discovered from the vault. Counts are facts, not estimates."""

    slug: str
    display_name: str
    area: str
    note_count: int = 0
    paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"slug": self.slug, "display_name": self.display_name, "area": self.area,
                "note_count": self.note_count}


def discover(paths: list[str], frontmatter: dict[str, str] | None = None) -> dict[str, Project]:
    """Build the project registry from a path list. `frontmatter` maps path -> projeto value.

    Generic by construction: no project name is ever referenced in code.
    """
    fm = frontmatter or {}
    projects: dict[str, Project] = {}
    for p in paths:
        s = project_of(p, fm.get(p))
        if not s:
            continue
        if s not in projects:
            projects[s] = Project(slug=s, display_name=(container_of(p) or s), area=area_of(p) or "")
        projects[s].note_count += 1
        projects[s].paths.append(p)
    return projects


def areas(paths: list[str]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for p in paths:
        a = area_of(p)
        if a:
            out[a] += 1
    return dict(sorted(out.items()))


# -- scope ------------------------------------------------------------------------------------
@dataclass
class Scope:
    """A parsed query scope. Empty projects+areas means global (whole brain)."""

    projects: frozenset[str] = frozenset()
    areas: frozenset[str] = frozenset()

    @property
    def is_global(self) -> bool:
        return not self.projects and not self.areas

    def label(self) -> str:
        if self.is_global:
            return GLOBAL_SCOPE
        parts = [f"projeto:{p}" for p in sorted(self.projects)] + [f"area:{a}" for a in sorted(self.areas)]
        return ",".join(parts)

    def matches(self, rel_path: str, frontmatter_projeto: str | None = None) -> bool:
        if self.is_global:
            return True
        if self.projects and project_of(rel_path, frontmatter_projeto) in self.projects:
            return True
        if self.areas and area_of(rel_path) in self.areas:
            return True
        return False


def parse_scope(spec: str | None) -> Scope:
    """Parse `projeto:a,projeto:b,area:50-Pessoal`. None/''/'global' -> global scope.

    Unknown prefixes are treated as a project slug so `scope=norteia` also works.
    """
    if not spec or spec.strip().lower() in {GLOBAL_SCOPE, "all", "*"}:
        return Scope()
    projects, area_set = set(), set()
    for raw in spec.split(","):
        token = raw.strip()
        if not token:
            continue
        key, _, value = token.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key in {"projeto", "project"} and value:
            projects.add(slug(value))
        elif key in {"area", "área"} and value:
            area_set.add(value)
        else:
            projects.add(slug(token))
    return Scope(frozenset(projects), frozenset(area_set))


def filter_paths(paths: list[str], scope: Scope, frontmatter: dict[str, str] | None = None) -> list[str]:
    fm = frontmatter or {}
    return [p for p in paths if scope.matches(p, fm.get(p))]

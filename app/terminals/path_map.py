"""Tradução host -> contêiner dos caminhos de projeto (Anamnésia rodando em Docker).

Problema: o usuário cola `C:\\Users\\YourUser\\Projetos_AI\\Meu Projeto`, mas o processo roda num contêiner Linux
onde `C:\\` não existe. Solução: `ANAMNESIA_PATH_MAP` lista pares `host=contêiner` separados por `;`::

    ANAMNESIA_PATH_MAP="C:/Users/YourUser/Projetos_AI=/projects;D:/Dados=/projects2"

O compose monta cada raiz do host (somente leitura) no contêiner. Só caminhos DENTRO dessas raízes são aceitos;
o caminho real (realpath, symlinks resolvidos) precisa continuar dentro da raiz do contêiner.

Códigos de erro (PathMapError.code): path_not_mapped, path_not_found, path_permission, path_invalid, path_escape.
Sem `ANAMNESIA_PATH_MAP` nada muda: o caminho nativo é usado como antes.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.terminals.projects import ProjectError

ENV_MAP = "ANAMNESIA_PATH_MAP"
ENV_HINT_VARS = "ANAMNESIA_PROJECTS_HOST / ANAMNESIA_PATH_MAP"
RECREATE_HINT = ("Adicione a pasta (ou uma raiz que a contenha) em ANAMNESIA_PROJECTS_HOST / ANAMNESIA_PATH_MAP e "
                 "recrie o contêiner (veja scripts/mgtest.py e docs/DOCKER.md).")

_DRIVE = re.compile(r"^([A-Za-z]):(?:/|$)")
_MNT = re.compile(r"^/(?:mnt/)?([A-Za-z])(?:/|$)")
_BAD_CHARS = re.compile(r'[<>"|?*\x00-\x1f]')


class PathMapError(ProjectError):
    """Erro específico e acionável; `code` é estável (API/UI), `roots` lista as raízes autorizadas."""

    def __init__(self, code: str, message: str, hint: str = "", roots: list[dict] | None = None):
        super().__init__(message)
        self.code, self.message, self.hint, self.roots = code, message, hint, roots or []


@dataclass(frozen=True)
class PathRoot:
    host: str        # forma de exibição, ex.: C:/Users/YourUser/Projetos_AI
    container: str   # ex.: /projects
    key: str         # host normalizado p/ comparação (NFC + casefold)

    def to_dict(self) -> dict:
        ok = _root_available(self.container)
        return {"host_path": self.host, "container_path": self.container, "available": ok,
                "read_only": ok and not os.access(self.container, os.W_OK)}


@dataclass(frozen=True)
class Translation:
    host_path: str        # caminho do host para exibir (canônico, barras normais); "" se não mapeado
    container_path: str   # caminho real (symlinks resolvidos) acessado pelo processo
    mapped: bool
    root_host: str = ""
    stable_key: str = ""  # base do id estável do projeto


def _root_available(path: str) -> bool:
    try:
        return os.path.isdir(path) and os.access(path, os.R_OK | os.X_OK)
    except OSError:
        return False


def _in_docker() -> bool:
    return os.environ.get("MG_IN_DOCKER") == "1" or Path("/.dockerenv").exists()


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _key(s: str) -> str:
    return _nfc(s).casefold()


def looks_like_host_path(raw: str) -> bool:
    """Caminho no estilo Windows (C:\\..., C:/..., \\\\?\\C:\\..., \\\\servidor\\share)."""
    s = (raw or "").strip().strip('"').strip("'")
    return bool(re.match(r"^(?:\\\\\?\\)?[A-Za-z]:[\\/]|^[A-Za-z]:$|^\\\\|^//[^/]", s))


def normalize_host_path(raw: str) -> str:
    """Forma canônica de exibição: `C:/Users/YourUser/Meu Projeto` (drive maiúsculo, barras normais, sem '/' final).

    Aceita `C:\\x`, `c:/x`, `\\\\?\\C:\\x`, `/c/x`, `/mnt/c/x` e UNC. Levanta path_invalid / path_escape ('..').
    """
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    if not s:
        raise PathMapError("path_invalid", "informe o caminho da pasta do projeto")
    s = re.sub(r"^(?:\\\\|//)\?[\\/]", "", s)
    if _BAD_CHARS.search(s):
        raise PathMapError("path_invalid", "o caminho contém caracteres inválidos (< > \" | ? * ou de controle)",
                           "copie o caminho direto do Explorador de Arquivos (Shift+clique direito > Copiar como caminho)")
    s = s.replace("\\", "/")
    if s.startswith("//?/"):
        s = s[4:]
        if s.upper().startswith("UNC/"):
            s = "//" + s[4:]
    unc = s.startswith("//") and not _DRIVE.match(s)
    m = _DRIVE.match(s)
    m2 = None if (m or unc) else _MNT.match(s)
    if m:
        drive, rest = m.group(1).upper(), s[2:]
    elif m2:
        drive, rest = m2.group(1).upper(), s[m2.end():]
    elif unc:
        drive, rest = "", s[1:]
    else:
        raise PathMapError("path_invalid", f"não é um caminho do host com unidade (ex.: C:\\Pasta\\Projeto): {raw!r}",
                           "informe o caminho completo, começando pela letra da unidade")
    parts = [p for p in rest.split("/") if p not in ("", ".")]
    if ".." in parts:
        raise PathMapError("path_escape", "o caminho contém '..' (travessia de diretório não é permitida)",
                           "informe o caminho completo e direto da pasta do projeto")
    body = "/".join(_nfc(p) for p in parts)
    if unc:
        return "//" + body
    return f"{drive}:/{body}" if body else f"{drive}:/"


def parse_path_map(raw: str | None = None) -> list[PathRoot]:
    """Interpreta ANAMNESIA_PATH_MAP (`host=contêiner;host=contêiner`). Pares malformados são ignorados."""
    raw = os.environ.get(ENV_MAP, "") if raw is None else raw
    roots: list[PathRoot] = []
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        host, _, cont = pair.rpartition("=")
        cont = cont.strip()
        try:
            h = normalize_host_path(host)
        except PathMapError:
            continue
        if cont:
            roots.append(PathRoot(h.rstrip("/") if len(h) > 3 else h, cont, _key(h.rstrip("/") if len(h) > 3 else h)))
    return sorted(roots, key=lambda r: -len(r.key))  # raiz mais específica primeiro


def active() -> bool:
    return bool(parse_path_map())


def roots_info() -> list[dict]:
    return [r.to_dict() for r in parse_path_map()]


def _within(child: str, root: str) -> bool:
    c, r = os.path.normcase(child), os.path.normcase(root).rstrip("\\/")
    return c == r or c.startswith(r + os.sep) or c.startswith(r + "/")


def _not_mapped(raw: str, roots: list[PathRoot]) -> PathMapError:
    lst = [r.to_dict() for r in roots]
    shown = ", ".join(r.host for r in roots) or "(nenhuma)"
    return PathMapError(
        "path_not_mapped",
        f"a pasta {raw!r} está fora das raízes autorizadas do Docker. Raízes disponíveis: {shown}.",
        RECREATE_HINT, lst)


def _step(base: str, comp: str) -> str:
    """Desce um componente; casefold/NFC como fallback (Windows ignora maiúsculas; o contêiner não)."""
    cand = os.path.join(base, comp)
    if os.path.lexists(cand):
        return cand
    want = _key(comp)
    try:
        with os.scandir(base) as it:
            hits = [e.name for e in it if _key(e.name) == want]
    except PermissionError as e:
        raise PathMapError("path_permission", f"sem permissão para ler a pasta {base}",
                           "ajuste as permissões da pasta no host (o contêiner a lê como somente leitura)") from e
    except OSError as e:
        raise PathMapError("path_not_found", f"pasta não encontrada: {base}") from e
    if len(hits) == 1:
        return os.path.join(base, hits[0])
    raise PathMapError("path_not_found", f"'{comp}' não existe em {base}" if not hits
                       else f"'{comp}' é ambíguo em {base} (várias pastas diferem só por maiúsculas)")


def _finish(real: str, root_container: str, root: PathRoot | None, host_disp: str, shown: str) -> Translation:
    if not os.path.isdir(real):
        raise PathMapError("path_invalid", f"o caminho não é uma pasta: {shown}", "informe a PASTA do projeto, não um arquivo")
    if not os.access(real, os.R_OK | os.X_OK):
        raise PathMapError("path_permission", f"sem permissão de leitura em {shown}",
                           "ajuste as permissões da pasta no host; o contêiner a lê como somente leitura")
    stable = f"host:{_key(host_disp)}" if host_disp else f"path:{os.path.normcase(real)}"
    return Translation(host_disp, real, bool(host_disp), root.host if root else "", stable)


def resolve_project_path(raw: str, roots: list[PathRoot] | None = None) -> Translation:
    """Traduz o caminho informado para o caminho acessível ao processo. Levanta PathMapError.

    Sem mapa ativo e fora de Docker: caminho nativo (comportamento histórico). Com mapa ativo: o caminho
    precisa estar dentro de uma raiz mapeada (host) ou já ser um caminho de contêiner dentro de uma raiz.
    """
    roots = parse_path_map() if roots is None else roots
    text = (raw or "").strip()
    if not roots:
        return _native(text)
    if looks_like_host_path(text) or (_MNT.match(text.replace("\\", "/")) and not os.path.exists(text)):
        try:
            return _from_host(text, roots)
        except PathMapError as e:
            if e.code != "path_not_mapped":
                raise
            try:  # já é um caminho do lado do contêiner (ex.: testes nativos no Windows)
                return _from_container(text, roots)
            except PathMapError as e2:
                raise (e if e2.code == "path_not_mapped" else e2) from None
    # já é um caminho do lado do contêiner?
    return _from_container(text, roots)


def _native(text: str) -> Translation:
    if _in_docker() and os.name != "nt" and looks_like_host_path(text):
        raise PathMapError(
            "path_not_mapped",
            f"o Anamnésia roda em Docker e não há raízes mapeadas (ANAMNESIA_PATH_MAP vazio): {text!r} não existe no contêiner.",
            RECREATE_HINT)
    try:
        real = Path(text).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as e:
        raise PathMapError("path_not_found", "o caminho não existe",
                           "confira se a pasta existe e se o caminho está completo") from e
    if not real.is_dir():
        raise PathMapError("path_invalid", "o caminho não é um diretório")
    return _finish(str(real), str(real), None, "", str(real))


def _from_host(text: str, roots: list[PathRoot]) -> Translation:
    host = normalize_host_path(text)
    k = _key(host)
    root = next((r for r in roots if k == r.key or k.startswith(r.key.rstrip("/") + "/")), None)
    if root is None:
        raise _not_mapped(host, roots)
    rel = [p for p in host[len(root.host):].split("/") if p]
    base_real = os.path.realpath(root.container)
    if not os.path.isdir(base_real):
        raise PathMapError("path_not_found",
                           f"a raiz {root.host} está configurada, mas não existe no contêiner ({root.container}).",
                           "a pasta do host não foi montada: " + RECREATE_HINT, [r.to_dict() for r in roots])
    cur = root.container
    for comp in rel:
        cur = _step(cur, comp)
        if not _within(os.path.realpath(cur), base_real):  # symlink evasivo no meio do caminho
            raise PathMapError("path_escape", f"'{comp}' aponta para fora da raiz autorizada {root.host}",
                               "links simbólicos que saem da raiz mapeada não são seguidos")
    if not os.path.lexists(cur):
        raise PathMapError("path_not_found", f"a pasta não existe: {host}",
                           "ela pode ter sido renomeada ou removida; confira o caminho no Explorador de Arquivos")
    real = os.path.realpath(cur)
    if not _within(real, base_real):
        raise PathMapError("path_escape", f"o caminho real fica fora da raiz autorizada {root.host}",
                           "links simbólicos que saem da raiz mapeada não são seguidos")
    # nome real (maiúsculas do disco) para exibição estável
    disp = root.host + ("/" + "/".join(Path(real).relative_to(base_real).parts) if real != base_real else "")
    shown = host
    return _finish(real, base_real, root, _nfc(disp) if _key(disp) == k else host, shown)


def _from_container(text: str, roots: list[PathRoot]) -> Translation:
    if _BAD_CHARS.search(text) or not text:
        raise PathMapError("path_invalid", "caminho inválido")
    if ".." in re.split(r"[\\/]", text):
        raise PathMapError("path_escape", "o caminho contém '..' (travessia de diretório não é permitida)")
    try:
        real = os.path.realpath(os.path.expanduser(text))
    except (OSError, ValueError) as e:
        raise PathMapError("path_invalid", "caminho inválido") from e
    for r in roots:
        base = os.path.realpath(r.container)
        if _within(real, base):
            if not os.path.lexists(real):
                raise PathMapError("path_not_found", f"a pasta não existe: {text}",
                                   "ela pode ter sido renomeada ou removida")
            rel = Path(real).relative_to(base).as_posix() if real != base else ""
            host = r.host + ("/" + rel if rel else "")
            return _finish(real, base, r, host, text)
    if looks_like_host_path(text):  # defensivo
        raise _not_mapped(text, roots)
    raise _not_mapped(text, roots)


def translate_stored(path: str) -> Translation | None:
    """Re-traduz um caminho de host gravado (registro antigo) quando o mapa agora o cobre; None se não der."""
    roots = parse_path_map()
    if not roots or not looks_like_host_path(path):
        return None
    try:
        return resolve_project_path(path, roots)
    except PathMapError:
        return None

"""Matcher mínimo de .gitignore (semântica do git: último padrão que casa vence; `!` re-inclui).

Suporta: comentários, `!`, `/` inicial (ancorado), `/` final (só diretórios), `*`, `?`, `[...]`, `**`.
Não suporta: escapes exóticos e `core.excludesFile` global (de propósito: só o que está no projeto).
"""
from __future__ import annotations

import re
from pathlib import Path


def _translate(pat: str) -> str:
    out: list[str] = []
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pat[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pat.find("]", i + 2)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = pat[i + 1:j]
                if body[:1] == "!":
                    body = "^" + body[1:]
                out.append("[" + body.replace("\\", "\\\\") + "]")
                i = j
        elif c == "\\" and i + 1 < n:
            i += 1
            out.append(re.escape(pat[i]))
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


class Rule:
    __slots__ = ("rx", "negate", "dir_only")

    def __init__(self, line: str):
        s = line.rstrip("\r\n")
        if not s.strip() or s.startswith("#"):
            raise ValueError("blank")
        s = re.sub(r"(?<!\\)\s+$", "", s)
        self.negate = s.startswith("!")
        _self_dir = True
        if self.negate:
            s = s[1:]
        self.dir_only = s.endswith("/")
        s = s.rstrip("/")
        if not s:
            raise ValueError("empty")
        self_dir_only = self.dir_only
        anchored = "/" in s
        s = s.lstrip("/")
        body = _translate(s)
        if anchored:
            # relativo ao diretório do .gitignore
            suffix = "(/.*)?" if self_dir_only else ""
            self.rx = re.compile("^" + body + suffix + "$")
        else:
            # casa um componente (ou subcaminho) em qualquer nível, com descendentes
            self.rx = re.compile("^(?:.*/)?" + body + "(/.*)?$")


class GitIgnore:
    """Regras de UM arquivo .gitignore, relativas ao diretório `base` (posix, relativo à raiz do projeto)."""

    def __init__(self, base: str, text: str):
        self.base = base.strip("/")
        self.rules: list[Rule] = []
        for line in text.splitlines():
            try:
                self.rules.append(Rule(line))
            except (ValueError, re.error):
                continue

    @classmethod
    def load(cls, directory: Path, base: str) -> "GitIgnore | None":
        f = directory / ".gitignore"
        try:
            if f.is_file() and f.stat().st_size <= 1024 * 1024:
                return cls(base, f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
        return None

    def verdict(self, rel: str, is_dir: bool) -> bool | None:
        """True = ignorado, False = re-incluído por `!`, None = sem opinião.

        Regra `pasta/` (dir-only) também ignora arquivos DENTRO dela (qualquer antecessor que case)."""
        if self.base:
            if not rel.startswith(self.base + "/"):
                return None
            rel = rel[len(self.base) + 1:]
        res: bool | None = None
        parts = rel.split("/")
        for r in self.rules:
            if r.rx.match(rel):
                res = not r.negate
        return res


def is_ignored(stack: list[GitIgnore], rel: str, is_dir: bool) -> bool:
    res = False
    for gi in stack:  # raiz -> folha: o mais profundo tem a palavra final
        v = gi.verdict(rel, is_dir)
        if v is not None:
            res = v
    return res

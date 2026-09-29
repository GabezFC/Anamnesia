#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lint determinístico e READ-ONLY de um vault Obsidian (proposta 0.3).

    python scripts/vault_lint.py [--vault PATH] [--json] [--max-note-chars N]

Sem `--vault` usa o vault configurado no projeto (mesma precedência do `vault-check`:
`MEMORY_GATEWAY_VAULT` > `OBSIDIAN_VAULT_PATH` > `data/synthetic_vault`).
Exit code 0 quando não há itens, 1 quando há. A correção é feita nota a nota, nunca aqui.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.vault_lint import MAX_NOTE_CHARS, lint  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="lint READ-ONLY do vault")
    p.add_argument("--vault", help="caminho do vault (default: vault configurado no projeto)")
    p.add_argument("--json", action="store_true", help="saída em JSON")
    p.add_argument("--max-note-chars", type=int, default=MAX_NOTE_CHARS,
                   help=f"limite de tamanho de nota (default {MAX_NOTE_CHARS})")
    a = p.parse_args(argv)

    from config.retrieval import resolve_vault_path, validate_vault_path
    try:
        vault = validate_vault_path(resolve_vault_path(a.vault))
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    report = lint(vault, max_note_chars=a.max_note_chars)
    if a.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.render())
    return 0 if report.total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

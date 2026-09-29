"""Lint do vault: uma nota por categoria, num vault temporário (nunca o vault real)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.obsidian import ObsidianVault
from app.services.vault_lint import CATEGORIES, MAX_NOTE_CHARS, lint

FULL_FM = """---
id: 20260912-1443
title: Nota completa
area: {area}
type: nota
tags: [exemplo]
status: ativo
created: 2026-09-12 14:43
updated: 2026-09-12 14:43{projeto}
---

# Nota completa

{body}"""


def _write(vault: Path, rel: str, text: str) -> None:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _mk(vault: Path, rel: str, *, area: str = "Projetos", extra_fm: str = "",
        body: str = "Corpo.\n", projeto: bool = True) -> None:
    _write(vault, rel, FULL_FM.format(
        area=area, projeto="\nprojeto: exemplo" if projeto else "", body=body))


def _clean_vault(tmp_path: Path) -> Path:
    """Vault mínimo sem nenhum item: 1 hub que entra em 1 nota."""
    v = tmp_path / "vault"
    _mk(v, "HOME.md", area="Inbox", projeto=False, body="Hub: [[nota-alvo]]\n")
    _mk(v, "30-Projetos/Exemplo/nota-alvo.md")
    return v


def _cat(report, category: str) -> list:
    return [f for f in report.findings if f.category == category]


def _paths(report, category: str) -> set[str]:
    return {f.path for f in report.findings if f.category == category}


# -- baseline -----------------------------------------------------------------------------------

def test_clean_vault_has_no_findings(tmp_path):
    report = lint(_clean_vault(tmp_path))
    assert report.total == 0, report.render()
    assert report.files == 2
    assert "OK" in report.render()


def test_report_is_deterministic(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/Quebrada nota.md", "sem frontmatter\n")
    first, second = lint(v), lint(v)
    assert first.to_dict() == second.to_dict()


def test_counts_cover_every_category(tmp_path):
    report = lint(_clean_vault(tmp_path))
    assert list(report.counts()) == [k for k, _ in CATEGORIES]
    assert all(v == 0 for v in report.counts().values())


def test_to_dict_is_json_serializable(tmp_path):
    report = lint(_clean_vault(tmp_path))
    assert json.loads(json.dumps(report.to_dict(), ensure_ascii=False))["total"] == 0


# -- one test per category ----------------------------------------------------------------------

def test_sem_frontmatter(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/sem-frontmatter.md", "# Só um título\n\nSem bloco.\n")
    report = lint(v)
    assert _paths(report, "sem_frontmatter") == {"20-Dev-IA/sem-frontmatter.md"}
    # sem frontmatter não gera também 8 complaints de campo faltando
    assert _cat(report, "campos_faltando") == []


def test_campos_faltando(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/incompleta.md",
           "---\nid: 20260912-1443\ntitle: X\narea: Dev-IA\n---\n\ncorpo\n")
    report = lint(v)
    finding = next(f for f in report.findings if f.path == "20-Dev-IA/incompleta.md"
                   and f.category == "campos_faltando")
    assert "type" in finding.detail and "created" in finding.detail


def test_area_incorreta(tmp_path):
    v = _clean_vault(tmp_path)
    _mk(v, "20-Dev-IA/area-errada.md", area="Trabalho")
    report = lint(v)
    assert _paths(report, "area_incorreta") == {"20-Dev-IA/area-errada.md"}
    assert "Dev-IA" in _cat(report, "area_incorreta")[0].detail


@pytest.mark.parametrize("folder,area", [
    ("00-Inbox", "Inbox"), ("10-Trabalho", "Trabalho"), ("20-Dev-IA", "Dev-IA"),
    ("30-Projetos/Exemplo", "Projetos"), ("40-Estudos", "Estudos"),
    ("50-Pessoal", "Pessoal"), ("70-Daily", "Daily"),
])
def test_area_batendo_com_a_pasta_nao_reprova(tmp_path, folder, area):
    v = tmp_path / "vault"
    _mk(v, f"{folder}/nota-ok.md", area=area, projeto=(area == "Projetos"))
    report = lint(v)
    assert _cat(report, "area_incorreta") == []


def test_projeto_ausente_em_pasta_de_projeto(tmp_path):
    v = _clean_vault(tmp_path)
    _mk(v, "30-Projetos/Exemplo/sem-projeto.md", projeto=False)
    report = lint(v)
    assert _paths(report, "projeto_ausente") == {"30-Projetos/Exemplo/sem-projeto.md"}


def test_projeto_nao_e_exigido_fora_das_pastas_de_projeto(tmp_path):
    v = _clean_vault(tmp_path)
    _mk(v, "20-Dev-IA/sem-projeto.md", area="Dev-IA", projeto=False)
    assert _cat(lint(v), "projeto_ausente") == []


def test_data_invalida(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/datas-ruins.md", """---
id: 2026-09-12
title: X
area: Dev-IA
type: nota
tags: []
status: ativo
created: 12/09/2026
updated: 2026-09-12
---

corpo
""")
    details = [f.detail for f in _cat(lint(v), "data_invalida")]
    assert len(details) == 3
    assert any("id:" in d for d in details)
    assert any("created:" in d for d in details)
    assert any("updated:" in d for d in details)


def test_datas_aceitas_quando_tem_hora(tmp_path):
    v = tmp_path / "vault"
    _mk(v, "20-Dev-IA/ok.md", area="Dev-IA", projeto=False)
    assert _cat(lint(v), "data_invalida") == []


def test_nome_fora_do_padrao(tmp_path):
    v = _clean_vault(tmp_path)
    for nome in ("Decisão de VPS.md", "nota_com_underscore.md", "norteia-SKILL.md"):
        _write(v, f"20-Dev-IA/{nome}", "---\nid: 20260912-1443\n---\n\ncorpo\n")
    assert _paths(lint(v), "nome_fora_do_padrao") == {
        f"20-Dev-IA/{n}" for n in
        ("Decisão de VPS.md", "nota_com_underscore.md", "norteia-SKILL.md")}


def test_excecoes_de_nome_de_passam(tmp_path):
    v = tmp_path / "vault"
    _write(v, "99-Templates/_nota.md", "---\nid: {{date:YYYYMMDD-HHmm}}\n---\n\n[[assim]]\n")
    _write(v, "70-Daily/2026-09-19.md", "---\nid: 20260919-1530\n---\n\nfoco\n")
    _write(v, "AGENTS.md", "# AGENTS\n")
    _write(v, "CLAUDE.md", "# CLAUDE\n")
    _write(v, "HOME.md", "---\nid: 20260912-0000\n---\n\nhub\n")
    assert _cat(lint(v), "nome_fora_do_padrao") == []


def test_wikilink_sem_alvo(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/quebrado.md", "---\nid: 20260912-1443\n---\n\n[[nota-que-nao-existe]]\n")
    report = lint(v)
    assert _paths(report, "wikilink_sem_alvo") == {"20-Dev-IA/quebrado.md"}
    assert "nota-que-nao-existe" in _cat(report, "wikilink_sem_alvo")[0].detail


def test_wikilinks_aceitos_que_resolvem(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/variacoes.md", "---\nid: 20260912-1443\n---\n\n" + "\n".join([
        "[[nota-alvo]]",
        "[[nota-alvo|com alias]]",
        "[[nota-alvo#secao]]",
        "[[nota-alvo#secao|com alias e ancora]]",
        "[[30-Projetos/Exemplo/nota-alvo]]",
    ]))
    assert _cat(lint(v), "wikilink_sem_alvo") == []


def test_wikilink_dentro_de_bloco_de_codigo_e_ignorado(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/codigo.md",
           "---\nid: 20260912-1443\n---\n\n```python\nx = '[[nota-que-nao-existe]]'\n```\n")
    assert _cat(lint(v), "wikilink_sem_alvo") == []


def test_exemplos_intencionais_de_wikilink_sao_ignorados(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "AGENTS.md", "# AGENTS\n\nEscreva assim: [[assim]] e [[]] e [[ ]].\n")
    _write(v, "99-Templates/_decisao.md", "---\nid: x\n---\n\nligue [[outro-qualquer]]\n")
    assert _cat(lint(v), "wikilink_sem_alvo") == []


def test_nomes_duplicados(tmp_path):
    v = _clean_vault(tmp_path)
    _mk(v, "20-Projetos/Exemplo/dup.md")
    _mk(v, "30-Projetos/Outro/dup.md")
    report = lint(v)
    finding = next(f for f in report.findings if f.category == "nomes_duplicados")
    assert finding.path == "20-Projetos/Exemplo/dup.md; 30-Projetos/Outro/dup.md"


def test_orfa(tmp_path):
    v = _clean_vault(tmp_path)
    _mk(v, "30-Projetos/Exemplo/sem-entrada.md")
    report = lint(v)
    assert _paths(report, "orfa") == {"30-Projetos/Exemplo/sem-entrada.md"}


def test_nota_com_entrada_nao_e_orfa(tmp_path):
    v = tmp_path / "vault"
    _mk(v, "HOME.md", area="Inbox", projeto=False, body="Hub: [[alvo]]\n")
    _mk(v, "30-Projetos/Exemplo/alvo.md")
    assert _cat(lint(v), "orfa") == []


def test_orfa_ignora_templates_daily_e_as_tres_notas_raiz(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "99-Templates/_nota.md", "---\nid: x\n---\n\ncorpo\n")
    _write(v, "70-Daily/2026-09-19.md", "---\nid: 20260919-1530\n---\n\nfoco\n")
    _write(v, "CLAUDE.md", "# CLAUDE\n")
    assert _cat(lint(v), "orfa") == []


def test_nota_grande(tmp_path):
    v = _clean_vault(tmp_path)
    _mk(v, "30-Projetos/Exemplo/gigante.md", body="x" * (MAX_NOTE_CHARS + 1))
    finding = _cat(lint(v), "nota_grande")[0]
    assert finding.path == "30-Projetos/Exemplo/gigante.md"
    assert str(MAX_NOTE_CHARS) in finding.detail


def test_limite_de_tamanho_e_configuravel(tmp_path):
    v = _clean_vault(tmp_path)
    _mk(v, "30-Projetos/Exemplo/media.md", body="y" * 500)
    assert _cat(lint(v), "nota_grande") == []
    grandes = {f.path for f in _cat(lint(v, max_note_chars=600), "nota_grande")}
    assert "30-Projetos/Exemplo/media.md" in grandes
    assert len(grandes) == 1, grandes


def test_arquivo_nao_md_na_raiz(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "Sem título.base", "{}")
    _write(v, "anotacoes.txt", "oi")
    assert _paths(lint(v), "arquivo_nao_md_raiz") == {"Sem título.base", "anotacoes.txt"}


def test_md_na_raiz_fora_dos_tres_permitidos(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "00-Inbox.md", "")
    report = lint(v)
    assert _paths(report, "md_fora_do_padrao_na_raiz") == {"00-Inbox.md"}
    # relatado uma vez só: o layout da raiz é o problema, não o nome nem o frontmatter
    assert _paths(report, "sem_frontmatter") == set()
    assert _paths(report, "nome_fora_do_padrao") == set()


def test_raiz_com_arquivos_ocultos_e_ignorada(tmp_path):
    v = _clean_vault(tmp_path)
    (v / ".obsidian").mkdir()
    _write(v, ".obsidian/config.md", "x")
    _write(v, ".DS_Store", "x")
    assert _cat(lint(v), "arquivo_nao_md_raiz") == []


# -- read-only guarantee ------------------------------------------------------------------------

def test_lint_nao_modifica_o_vault(tmp_path):
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/quebrado.md", "[[nao-existe]]\n")
    before = ObsidianVault(v).state_hash()
    lint(v)
    assert ObsidianVault(v).state_hash() == before


def test_modulo_nao_tem_operacao_de_escrita():
    import inspect

    import app.services.vault_lint as vl
    src = inspect.getsource(vl)
    for verb in ("open(", ".write_text(", ".write_bytes(", "unlink(", "mkdir(", "rmtree("):
        assert verb not in src, f"vault_lint não pode conter {verb}"


# -- CLI ----------------------------------------------------------------------------------------

def test_cli_registra_o_subcomando():
    from app.cli.main import build_parser
    args = build_parser().parse_args(["vault-lint", "--vault", "C:/x", "--json"])
    assert args.cmd == "vault-lint" and args.vault == "C:/x" and args.json is True


def test_script_e_cli_rodam(tmp_path, capsys):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import vault_lint as script

    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/quebrado.md", "[[nao-existe]]\n")
    assert script.main(["--vault", str(v), "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["wikilink_sem_alvo"] == 1
    assert script.main(["--vault", str(v)]) == 1
    assert "wikilink_sem_alvo" in capsys.readouterr().out
    assert script.main(["--vault", str(tmp_path / "nao-existe")]) == 2


def test_cli_vault_lint_comando_real(tmp_path, capsys):
    from app.cli.main import main
    v = _clean_vault(tmp_path)
    _write(v, "20-Dev-IA/quebrado.md", "[[nao-existe]]\n")
    with pytest.raises(SystemExit) as exc:
        main(["vault-lint", "--vault", str(v)])
    assert exc.value.code == 1
    assert "wikilink_sem_alvo" in capsys.readouterr().out


def test_vault_lint_default_e_zero(tmp_path, capsys):
    from app.cli.main import main
    v = _clean_vault(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["vault-lint", "--vault", str(v), "--json"])
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["total"] == 0

# ANAM-010 — injection_screen: fronteira de palavra + PT-BR

Fixture: `tests/fixtures/anam010_injection_cases.json` (13 positivos EN/PT, 11 benignos técnicos).
Métrica: "strong" = algum sinal `strong:`/`hidden:`; "suspicious" = qualquer sinal (over-inclusivo por desenho).

| Medida | ANTES (substring) | DEPOIS (regex \b + NFKC/casefold) |
|---|---|---|
| FP benignos strong | 5/11 (45%) | 0/11 |
| FP benignos suspicious (weak/imperativo) | 6/11 | 3/11 |
| FN positivos strong | 1/13 (paráfrase PT "Abandone as regras anteriores") | 0/13 |
| FN positivos suspicious | 0/13 | 0/13 |

Meta: FP ≤ 1/9 e paráfrase PT detectada — atingida.

Mudanças: padrões strong viraram regex com `\b` sobre texto NFKC + casefold + sem zero-width + sem diacríticos
+ espaços colapsados; vocabulário técnico solto (override, bypass, act as, system prompt) deixou de ser strong
e exige contexto de ataque (override/bypass viram weak ou exigem alvo; system prompt só strong com verbo de
exfiltração). Novos padrões PT (abandone/descarte/anule + instruções/regras + anteriores/acima etc.).
API pública (`screen`, `Screen`, `should_ask_injection`, `normalized_views`, `INJECTION_SCREEN_VERSION`) e formato
de retorno inalterados (versão mantida em `inj-screen-v2` porque `test_ana036_injection_corpus` a fixa).
Reprodução: `pytest tests/test_anam010_injection_screen.py`.

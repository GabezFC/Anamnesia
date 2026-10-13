# Policy e enforcement (Onda 4d: ANA-169, 173, 174, 176, 182, 192)

Tudo abaixo é **opt-in** (padrão desligado) exceto o rótulo informativo `enforcement` (ANA-169).

| Item | Flag | O que faz | Limite honesto |
|---|---|---|---|
| ANA-169 | (sempre) | `summary.json -> steps[].enforcement`: `hard` (InProcessModelLauncher, sem tools), `soft` (TerminalLauncher/PTY), `best_effort` (demais) | Só rótulo; não bloqueia nada |
| ANA-173 | `ANAMNESIA_ENFORCE_ROLES=1` | `enforcement.enforce()` aplica `roles.check_action` e grava `policy_denied` na trilha encadeada; `readonly_argv()` monta flags read-only | `claude --permission-mode plan` verificado no `--help`; `codex -s read-only` **não verificado** (codex ausente) => nunca `hard`. O orquestrador ainda não chama `enforce()` no caminho do PTY |
| ANA-174 | `ANAMNESIA_DIFF_GATE=1` | `diff_gate.verify_diff/gate_worktree`: confere `git diff` + untracked contra o escopo e reverte | Função pronta e testada em repo temporário; não está ligada ao orquestrador |
| ANA-176 | `ANAMNESIA_POLICY=off\|audit\|enforce` | `app.policy.engine.check/require`, regras em `config/policy.yaml`, default-deny para write/exec/pay/escalate, auditoria jsonl com hash encadeado (`verify_chain`) | Pontos de efeito colateral ainda **não** passam por `check`: launchers, worktrees, `memory_save` (ANA-067 segue PARCIAL) |
| ANA-182 | `ANAMNESIA_HANDOFF=1` | `handoff.json` por etapa validado por schema próprio; `summarize_for_next` | Não injetado no prompt do próximo passo ainda |
| ANA-192 | `ANAMNESIA_TOOL_PROFILE` | `app/policy/tools_manifest.py`: escopo/risco por tool, perfis `restricted`/`readonly`, teste "tools expostas == manifesto" | O perfil não filtra o servidor MCP em execução; é só o manifesto + teste |

Auditoria: `logs/policy_audit.jsonl` (ou `ANAMNESIA_POLICY_AUDIT`). Nunca grava prompts, argv ou payloads. Separada de `exec_audit.jsonl`.

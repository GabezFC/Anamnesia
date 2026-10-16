# Laya — decisor local não generativo (ANAM-042)

Laya (`convaiinnovations/laya`, **Apache-2.0**, Convai Innovations) recebe um `state` e perguntas tipadas
(`choice` / `score` / `noul`) e devolve probabilidades calibradas + `confidence`, sem gerar texto.
No Anamnésia ela é o decisor **local** para três usos: relevância de resultados, sensibilidade (privacidade)
e triagem de escrita. **Medição e decisão:** [`docs/bench/anam-042-laya.md`](../bench/anam-042-laya.md).

## Resumo da decisão

| Pergunta | Resposta (medida, conjunto sintético) |
|---|---|
| Laya sozinha filtra relevância melhor que o baseline/JEV? | **Não.** AUC 0,64–0,68 contra 0,975 do casamento lexical do `prefilter`. |
| Laya+JEV em cascata economiza JEV? | **Não de forma útil**: p/ recall ≥ 0,95 escalona 65–94% ao JEV. JEV real não foi medido. |
| Padrão | `graphify_jev_opt` segue padrão. `graphify_laya` e `graphify_laya_jev` são **opt-in**. |
| Onde Laya é obrigatória | Sensibilidade (`classify_privacy`/`must_stay_local`, fail-closed) e sinal extra na escrita (`MG_LAYA_WRITE_TRIAGE`). |

## Fatos verificados (2026-10-15)

- **Pacote PyPI `laya` 0.4.8**, `requires-python >=3.10`, licença Apache-2.0; deps: `torch>=2`, `transformers>=4.48`, `safetensors`, `huggingface_hub`, `numpy`. Extras: `serve` (fastapi/uvicorn), `onnx`, `mcp`, `fast`, etc.
- API: `from laya import Router; Router(models={...}, default="multilingual", device=None, preload=False, max_loaded=2, ...)`; `router.predict(state, questions, model=None, ...)`; `router.predict_batch(requests, batch_size=None)`; `router.decide(...)` (schemas). Resultado: `answers[nome] = {type, choice, probabilities, confidence, answer_confidence, action}`, `routing = {model, repo, reason, detection{language,...}}`, `usage`.
- O `Router` escolhe o checkpoint pelo idioma do `state` (inglês → `english`; resto → `multilingual`). `Router(models={"multilingual": <dir>, "english": <dir>})` aceita **diretórios locais** (usado aqui, offline).
- `laya-serve` (extra `serve`): `POST /v1/systemone` no formato do TypeSafe; **liga em `0.0.0.0:8000` sem autenticação por padrão** → aqui sempre `LAYA_HOST=127.0.0.1` e porta própria (nunca 8000). `LAYA_EXTRA_MODELS` registra checkpoints locais; `LAYA_PRELOAD=0` carrega sob demanda. Verificado: serve + `LayaBackend` modo `serve` funcionam (1ª chamada ~7,9 s carregando, depois ~260 ms para 2 candidatos).
- Checkpoints e **revisões pinadas** (HfApi, 2026-10-15): `laya-multilingual` `1720e3e3357cfe1e281542e223f8273b0890ca34` (643,8 MB, mmBERT-base, 322M); `laya` (inglês, ModernBERT-large 421M) `7b928d828b7b0e022f929d9bd2e44165aa270148` (842,6 MB). Total baixado ≈ 1,7 GB (limite 3 GB). Pesos em `data/local_ai/models/laya-multilingual|laya-english` (ignorados pelo Git).
- Avisos do upstream que moldaram o código: `noul` pode seguir os rótulos e não o estado → **todas as perguntas são `choice` com chaves neutras A/B(/C)**; `act_probability` é inútil → usamos `confidence`; Laya é superconfiante → `MG_LAYA_TEMPERATURE` (refit por dados próprios).
- Colibrì só serve o checkpoint inglês/typed-decisions em `/v1/systemone` (multilingual não suportado) → para PT-BR use `inproc` ou `laya-serve`.
- Aviso do próprio pacote ao carregar o multilingual: *"this checkpoint ships invalid temperatures … using choice:11+ … -> 0.5. Treat confidence from the affected entries as uncalibrated"* (RuntimeWarning). Vale para perguntas `choice` com 11+ opções; as nossas têm 2–3 opções.

## Instalação (venv separado; NUNCA no `.venv` do projeto)

```bash
uv venv <scratch>/laya-venv --python 3.12
uv pip install --python <scratch>/laya-venv/Scripts/python.exe torch --index-url https://download.pytorch.org/whl/cpu
uv pip install --python <scratch>/laya-venv/Scripts/python.exe "laya[serve]==0.4.8" python-dotenv psutil
# pesos, com revisão pinada (ver config/laya.py: LAYA_REVISIONS):
python -c "from huggingface_hub import snapshot_download as s; \
  s('convaiinnovations/laya-multilingual', revision='1720e3e3357cfe1e281542e223f8273b0890ca34', local_dir='data/local_ai/models/laya-multilingual')"
```

Para usar `inproc` no gateway o Python do gateway precisa importar `laya` (instale no ambiente em que o Gateway roda **se** quiser o modo `inproc`; o `.venv` de desenvolvimento não precisa). Alternativa sem dependências no gateway: suba `laya-serve` em loopback e use `MG_LAYA_MODE=serve`:

```bash
LAYA_HOST=127.0.0.1 LAYA_PORT=8765 LAYA_PRELOAD=0 HF_HUB_OFFLINE=1 \
LAYA_EXTRA_MODELS='{"multilingual":"data/local_ai/models/laya-multilingual"}' laya-serve
# .env: MG_LAYA_MODE=serve  MG_LAYA_SERVE_URL=http://127.0.0.1:8765  MG_LAYA_FORCE_MODEL=multilingual
```

## Código

| Arquivo | Papel |
|---|---|
| `config/laya.py` | `LayaConfig` (env `MG_LAYA_*`), revisões pinadas, versão do prompt |
| `app/services/laya_decider.py` | `LayaBackend` (inproc/serve/off; contrato `JevBackend.evaluate`), `LayaService` (contrato `Judge`), `classify_privacy`/`must_stay_local`, `triage_write` |
| `app/retrieval/pipelines_laya.py` | pipelines `graphify_laya` e `graphify_laya_jev` (registrados em `PIPELINES`) |
| `app/memory_store/lifecycle.py` | `save_checked` chama `triage_write` se `MG_LAYA_WRITE_TRIAGE` ≠ `off` |
| `scripts/bench_laya.py` | conjunto rotulado + medição; saída `docs/bench/anam-042-laya.md` |

### Modos (`MG_LAYA_MODE`)

`inproc` (pacote importável + pesos) · `serve` (HTTP loopback, porta própria; recusa host não-loopback e porta 8000) · `off` · `auto` (inproc → serve → off). **Nada cai para outro modo em silêncio:** `LayaBackend.status()` informa `effective_mode` e `reason`; as métricas dos pipelines trazem `laya_mode`, `laya_fallback`, `laya_error`. Carregamento preguiçoso (nada carrega no import). `MG_LAYA_FORCE_MODEL=multilingual` evita carregar o checkpoint inglês (~0,8 GB).

### (a) Relevância

`LayaService.evaluate(query, candidates)`: pergunta `choice` de 3 vias (A = contém o item/fato pedido; B = mesmo assunto sem o item; C = não relacionado), `P(A)` calibrada por temperatura → `KEEP` (≥ `MG_LAYA_KEEP_THRESHOLD`) / `REVIEW` / `DROP` (< `MG_LAYA_DROP_THRESHOLD`), mesmos rótulos do JEV (`survives`, `judge_health` funcionam). Candidatos com sinal do `injection_screen` recebem a pergunta de injeção do Laya; `p ≥ MG_LAYA_INJECTION_THRESHOLD` → `QUARANTINE`; Laya fora do ar + sinal lexical → `QUARANTINE` (fail-closed).

- `graphify_laya`: graphify → prefilter → Laya. Sem tokens pagos. Laya indisponível: `MG_LAYA_FAILURE_MODE` (`fail_open` passa **sinalizado** com `laya_fallback=1`; `fail_closed` nada passa). Safety-net do `graphify_jev` (nunca contexto vazio, nunca sobrepõe QUARANTINE).
- `graphify_laya_jev` (cascata; consta em `JEV_PIPELINES` porque paga o JEV nos escalonados): Laya em todos; vão ao JEV os incertos (`p` entre `drop` e `keep`, ou `confidence < MG_LAYA_MIN_CONFIDENCE`) e os `KEEP` com sinal lexical de injeção. Laya fora do ar ⇒ **tudo** escalona ao JEV (≡ `graphify_jev`) com `laya_fallback=1`.
- Fora do roteamento `auto`: nenhum plano do otimizador escolhe esses pipelines; escolha explícita.

### (b) Privacidade — consumo pelo roteamento (ANAM-033)

```python
from app.services.laya_decider import classify_privacy, must_stay_local
v = classify_privacy(texto)      # PrivacyVerdict(private, score, source, signals, laya_available)
if must_stay_local(texto): ...   # True => só provider local (generate(..., private=True))
```

Regras determinísticas (CPF, CNPJ, e-mail, telefone BR, cartão com Luhn, chaves de API, chave privada, `senha=`) **sempre vencem**; Laya acrescenta o que regra não vê (limiar `MG_LAYA_PRIVACY_THRESHOLD`, recall-first). Laya **desligado por configuração** ⇒ `source="rules_only"` (explícito). Laya **ligado mas falhando** ⇒ `private=True` (`fail_closed`, a menos que `MG_LAYA_PRIVACY_FAILURE=rules_only`). `router.py` não foi editado: a ANAM-033 deve chamar `must_stay_local`.

### (c) Escrita de memória

`triage_write(texto)` combina `injection_screen` (fonte de verdade) com perguntas de injeção/lixo do Laya. Invariantes: regras suspeitas ⇒ nunca `allow`; Laya só **eleva** severidade; Laya fora ⇒ regras decidem e `reasons` traz `laya_unavailable`. `MG_LAYA_WRITE_TRIAGE=off` (padrão: comportamento antigo, sem custo), `warn` (anexa `triage` ao retorno de `save_checked`), `block` (recusa a escrita: `action="blocked_by_triage"`). Na medição, Laya **não superou** as regras para injeção (F1 0,69 vs 0,88) — por isso o padrão é `off`.

## Calibração

`MG_LAYA_TEMPERATURE` reescala `P(A)` (T>1 suaviza). Refit: `scripts/bench_laya.py` ajusta T por NLL na metade de calibração (T=1,2–1,4 nos dados sintéticos; ganho de F1 desprezível). Limiares padrão (relevância 0,25/0,10; privacidade 0,10; injeção 0,90) vêm da metade de calibração do conjunto sintético — **recalibre com dados seus**.

## Reproduzir a medição

```bash
<laya-venv>/Scripts/python.exe scripts/bench_laya.py --build    # benchmark/laya_labeled.json (determinístico, seed 42)
<laya-venv>/Scripts/python.exe scripts/bench_laya.py --score    # ~5 min em CPU
<laya-venv>/Scripts/python.exe scripts/bench_laya.py --report   # docs/bench/anam-042-laya.md
```

## Não verificado / riscos

- JEV real (TypeSafe) não foi chamado: a cascata foi medida só com limites passam/caem.
- Sem GPU: latências são de CPU (p50 ≈ 225 ms/candidato isolado, ≈ 230–280 ms/candidato em lote — **não** os ~33 ms do upstream, que presumem hardware/otimização próprios).
- RAM medida em CPU fp32: ≈ 1,6–1,7 GB só com o multilingual; ≈ 3,3 GB com os dois checkpoints carregados.
- Conjunto sintético pequeno (192 pares de relevância, 40 de privacidade, 30 de escrita); EN por gabarito sobre notas mistas PT/EN.
- A privacidade do Laya perde casos óbvios (ex.: "minha esposa está em tratamento de depressão" → p=0,02): **não é garantia de privacidade**; use junto com as regras e com `privacy_failure=fail_closed`.
- `laya-serve` expõe `0.0.0.0:8000` sem auth por padrão; sempre `LAYA_HOST=127.0.0.1`, porta própria, `LAYA_API_KEY` se houver qualquer exposição.

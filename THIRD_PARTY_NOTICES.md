# Third-party notices

Complementa `THIRD_PARTY_LICENSES.md` (dependências Python, gerado por `scripts/gen_third_party_licenses.py`).
Não é aconselhamento jurídico; vale a licença do componente na origem. Política: `app/services/license_policy.py`
(testada em `tests/test_anam026_release.py`).

| Componente | Licença | Uso no projeto | Redistribuído aqui? | Verificação |
|---|---|---|---|---|
| Colibrì (runtime local) | Apache-2.0 | `app/services/local_ai/colibri.py`, processo externo em porta própria | Não (instalado pelo usuário) | `Example Colibri/colibri/LICENSE` (Apache 2.0) |
| Laya (modelos de decisão) | Apache-2.0 | `app/services/laya_decider.py`, `config/laya.py` | Não (pesos em `data/local_ai/models/`, fora do Git) | front-matter `license: apache-2.0` do README do modelo |
| ds4 | MIT | integração externa, onde aplicável | Não | Informado na tarefa ANAM-026; **não verificado no repositório** — confirmar na origem |
| Provence (`naver/provence-reranker-debertav3-v1`) | CC BY-NC-ND 4.0 | estágio opcional `provence` | Não | Só uso pessoal/não comercial; desligado por padrão; nunca em wheel/exe |
| Qwen (modelos com Qwen Community License) | Restrita | Só se o usuário escolher; o catálogo marca `UNVERIFIED` quando a licença não foi confirmada | Não | Exige opt-in e leitura da licença |

Allow-list: Apache-2.0, MIT, BSD, PSF livres; MPL-2.0 como dependência sem modificação; NC/Qwen Community somente
opcionais e avisados; licença desconhecida (`null`/`UNVERIFIED`) não entra em produção (`config/model_catalog.json`, `rules`).

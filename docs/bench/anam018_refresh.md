# ANAM-018 — refresh do vault (AUD-010/011)

Vault sintético de 5.000 notas (criado em scratch, removido ao fim) — `python docs/bench/anam018_bench.py 5000`, NTFS, mediana de 7.

| Operação | Antes | Depois |
|---|---|---|
| checagem de frescor (fingerprint) | 590,5 ms (`os.walk`+`realpath`+`stat` por nota) | **76,6 ms** (`scandir`, stat da listagem) ≈ 7,7× |
| refresh após editar 1 nota | fingerprint + rebuild completo ≈ 30,9 s + limpa TODO o cache | **76–135 ms** (reindexa só a nota; invalida só entradas afetadas) |

Mecanismo: `app/gateway/vault_manifest.py` (manifesto `{rel:(mtime_ns,size)}`, mesma tupla de `fingerprint()`), diff added/changed/removed, `DELETE/INSERT` por arquivo no FTS5, `ResultCache.invalidate_where` (derruba entrada se nota entregue mudou/sumiu ou se nota nova/alterada contém termo da consulta, sem acento). Fallback para o caminho antigo (rebuild completo + `clear()`) se: symlink/junction, erro de E/S, diff > 25 % ou > 500 arquivos, baseline sem conexão. A chave de cache não embute mais o fingerprint (usa `_cache_epoch`, incrementado só no wipe total); a correção continua garantida por `guard_valid` (re-hash dos arquivos entregues) em todo hit.

Limites: o scan ainda é O(N) (sem watcher ReadDirectoryChangesW — proposta original do AUD-010; não implementado, sem nova dependência). Hit-rate com 1 escrita/min em 5k notas não foi medido com tráfego real (apenas testes unitários de seletividade).

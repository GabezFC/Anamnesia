# ANAM-030/031 - detector de hardware e catálogo de modelos

## Detector real (2026-10-15, `python -m app.services.hw_profile`, sem psutil/pynvml -> nvidia-smi)
- CPU: AMD Ryzen 7 5700G, 8c/16t
- RAM: total 39,79 GiB (= ~42,7 GB decimais); livre = min(física 24,57; commit 24,23) = 24,23 GiB
- GPU: RTX 3060, VRAM 12,0 GiB (livre 10,55), sm_86, driver 616.92
- Disco C: livre 617,4 GiB (~663 GB decimais; o golden dizia ~665 GB)
- hw_fingerprint: `73bc8a0fb8125484` (só identidade: OS, CPU, RAM total arredondada, GPUs/VRAM/cc; exclui livres e driver)

Throughput de disco: opt-in (`--measure-disk`), não executado aqui; cache do SO infla a leitura.

## Catálogo
- 28 modelos importados (apenas `verified_fields`); 2 sem nenhum campo verificado ficam fora.
- 10 com `license_status=UNVERIFIED` (inclui todos Llama/Gemma por D-3, qwen3.6, qwen3-embedding-8b, qwen3.5-122b): bloqueados no modo comercial.
- `revision_sha` = null em todos (a semente não registra SHA; precisa consulta ao HF). `min_vram_gb` = null (não verificado); `min_ram_gb` só gpt-oss-20b (16, cartão HF).
- `size_gb` = VENDOR-REPORTED (Ollama).

"""ANAM-018: latência de refresh em vault sintético grande (criado em scratch). Uso: python docs/bench/anam018_bench.py [N]"""
import os, shutil, statistics as st, sys, tempfile, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.gateway.optimizer import MemoryOptimizer
from app.gateway.vault_manifest import scan_manifest
from app.retrieval.baseline import BaselineIndex
from app.services.obsidian import ObsidianVault
from config.optimizer import OptimizerConfig

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
root = Path(os.environ.get("TMPDIR", tempfile.gettempdir())) / f"anam018_vault_{N}"
shutil.rmtree(root, ignore_errors=True)
for i in range(N):
    p = root / f"d{i % 100}" / f"n{i}.md"; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# Nota {i}\n\n## Secao\n\ntexto sintetico {i} palavra{i % 50} contexto alfa beta gama\n", encoding="utf-8")
v = ObsidianVault(root)

def t(f, n=7):
    xs = []
    for _ in range(n):
        s = time.perf_counter(); f(); xs.append((time.perf_counter() - s) * 1000)
    return round(st.median(xs), 1)

print(f"notas={N}")
print("fingerprint antigo (ms):", t(v.fingerprint))
print("manifesto novo     (ms):", t(lambda: scan_manifest(v)))

class GW: pass
gw = GW(); gw.vault = v; gw.baseline = BaselineIndex(v)
s = time.perf_counter(); gw.baseline.build(); print("build completo     (ms):", round((time.perf_counter() - s) * 1000, 1))
opt = MemoryOptimizer(OptimizerConfig(refresh_interval_s=0.0)); opt.mark_built(v.fingerprint()); opt.ensure_fresh(gw)
res = []
for k in range(5):                      # refresh após editar 1 nota (caminho novo)
    p = root / "d1" / f"n{k * 100 + 1}.md"; p.write_text(p.read_text(encoding="utf-8") + f"\nedit {k}\n", encoding="utf-8")
    st_ = p.stat(); os.utime(p, ns=(st_.st_atime_ns, st_.st_mtime_ns + (k + 1) * 3_000_000_000))
    s = time.perf_counter(); m = opt.ensure_fresh(gw); res.append((round((time.perf_counter() - s) * 1000, 1), m.get("index_incremental")))
print("refresh c/ 1 nota editada (ms, incremental?):", res)
shutil.rmtree(root, ignore_errors=True)

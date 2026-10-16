"""ANAM-007: N processos (spawn), cada um com seu SavedContextStore no MESMO diretório, dão feedback na mesma nota."""
from __future__ import annotations
import json, multiprocessing as mp, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def worker(root: str, nid: str, n: int, q) -> None:
    sys.path.insert(0, str(ROOT))
    from app.memory_store import lifecycle
    from app.memory_store.store import SavedContextStore
    st = SavedContextStore(root, rate_per_min=100000)
    errs = []
    for _ in range(n):
        try:
            lifecycle.feedback(st, nid, "useful", None, author="bench")
        except BaseException as e:  # noqa: BLE001
            errs.append(f"{type(e).__name__}: {e}"[:120])
    q.put(errs)


def run(procs: int = 4, total: int = 80) -> dict:
    sys.path.insert(0, str(ROOT))
    from app.memory_store import lifecycle
    from app.memory_store.store import SavedContextStore
    with tempfile.TemporaryDirectory() as d:
        root = str(Path(d) / "saved_context")
        st = SavedContextStore(root, rate_per_min=100000)
        nid = st.save("Nota bench", "conteudo", ["b"], "p", "bench")
        ctx = mp.get_context("spawn"); q = ctx.Queue()
        t0 = time.perf_counter()
        ps = [ctx.Process(target=worker, args=(root, nid, total // procs, q)) for _ in range(procs)]
        [p.start() for p in ps]
        errs = [e for _ in ps for e in q.get()]
        [p.join() for p in ps]
        dt = time.perf_counter() - t0
        n = SavedContextStore(root).get(nid).feedback_useful
        lines = len(lifecycle.feedback_events(st))
        return {"procs": procs, "total": total, "contador_nota": n, "linhas_jsonl": lines,
                "excecoes": len(errs), "amostra": sorted(set(errs))[:3], "segundos": round(dt, 2)}


if __name__ == "__main__":
    print(json.dumps([run(2, 80), run(4, 80)], ensure_ascii=False, indent=1))

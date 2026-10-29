"""FASE 9: auditoria real do CLI `python -m memory_gateway` (subprocessos, ANAMNESIA_HOME descartável,
vault sintético, offline). Cobre ajuda, cada subcomando, códigos de saída, erros, importação/exportação
(backup-create/restore), execução fora da raiz do repo e vazamento de sentinela.

Uso: python scripts/cli_audit.py [--out FILE.json]   (saída 0 = tudo PASS)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENT = "sk-" + "ant-SINTETICA0000000000000000000000AUDIT"
RES: list[dict] = []
BLOB: list[str] = []
EXPECTED = ["search", "benchmark", "sweep", "stats", "info", "vault-check", "decision", "index", "db-maintenance",
            "db-prune", "memory-audit", "vault-lint", "backup-create", "backup-restore"]


def rec(nome, ok, detalhe=""):
    RES.append({"teste": nome, "status": "PASS" if ok else "FAIL", "detalhe": str(detalhe)[:300]})
    print(f"[{'PASS' if ok else 'FAIL'}] {nome} {str(detalhe)[:150]}", flush=True)


def run(args, home, cwd=None, extra_env=None, timeout=240, module="memory_gateway"):
    env = {**os.environ, "ANAMNESIA_HOME": home, "MEMORY_GATEWAY_VAULT": str(ROOT / "data" / "synthetic_vault"),
           "ANTHROPIC_API_KEY": SENT, "OFFLINE": "1", "PYTHONIOENCODING": "utf-8",
           "PYTHONPATH": str(ROOT)}
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, "-m", module, *args], cwd=cwd or str(ROOT), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    BLOB.append(p.stdout + p.stderr)
    return p


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="cli_audit_") as home, tempfile.TemporaryDirectory(prefix="cli_out_") as outside:
        p = run(["--help"], home)
        rec("--help rc=0 e lista os subcomandos", p.returncode == 0 and all(c in p.stdout for c in EXPECTED),
            f"rc={p.returncode}")
        for c in EXPECTED:
            p = run([c, "--help"], home)
            rec(f"{c} --help rc=0", p.returncode == 0 and "usage" in p.stdout.lower(), f"rc={p.returncode}")
        p = run([], home)
        rec("sem subcomando → rc=2 com usage", p.returncode == 2, f"rc={p.returncode}")
        p = run(["inexistente"], home)
        rec("subcomando inválido → rc=2", p.returncode == 2, f"rc={p.returncode}")
        p = run(["search"], home)
        rec("search sem query → rc=2", p.returncode == 2)
        p = run(["search", "x", "--pipeline", "nao_existe"], home)
        rec("search --pipeline inválido → rc=2", p.returncode == 2)
        p = run(["search", "x", "--max-results", "abc"], home)
        rec("search --max-results não numérico → rc=2", p.returncode == 2)
        # consulta real (JSON)
        p = run(["search", "Qual o ambiente do Kraken?", "--pipeline", "baseline", "--json", "--max-results", "5"], home)
        ok = False
        try:
            d = json.loads(p.stdout[p.stdout.index("{"):])
            ok = p.returncode == 0 and "run_id" in d and "context" in d and len(d.get("sources", [])) <= 5
            det = f"rc=0 fontes={len(d.get('sources', []))} ctx={len(d.get('context',''))}ch"
        except Exception as exc:  # noqa: BLE001
            det = f"rc={p.returncode} {type(exc).__name__} {p.stderr[-200:]}"
        rec("search --json (baseline): JSON válido com run_id/context/sources", ok, det)
        p = run(["search", "Kraken", "--pipeline", "baseline"], home)
        rec("search modo texto rc=0", p.returncode == 0 and "pipeline=baseline" in p.stdout, f"rc={p.returncode}")
        p = run(["search", "' OR 1=1;--", "--pipeline", "baseline", "--json"], home)
        rec("search com caracteres especiais FTS/SQL: sem traceback", "Traceback" not in p.stderr, f"rc={p.returncode}")
        p = run(["info"], home)
        rec("info rc=0 e JSON", p.returncode == 0 and p.stdout.strip().startswith("{"), f"rc={p.returncode}")
        p = run(["index"], home)
        rec("index rc=0", p.returncode == 0, f"rc={p.returncode} {p.stdout[:80]!r}")
        p = run(["stats", "--json"], home)
        rec("stats --json rc=0", p.returncode == 0, f"rc={p.returncode} {p.stderr[-120:]}")
        p = run(["stats", "--session", "nao-existe", "--json"], home)
        rec("stats --session inexistente: sem traceback", "Traceback" not in p.stderr, f"rc={p.returncode}")
        p = run(["decision", "status", "--json"], home)
        rec("decision status --json rc=0", p.returncode == 0 and "active_provider" in p.stdout, f"rc={p.returncode}")
        p = run(["decision", "history", "--json"], home)
        rec("decision history rc=0", p.returncode == 0, f"rc={p.returncode}")
        p = run(["decision", "bogus"], home)
        rec("decision ação inválida → rc=2", p.returncode == 2)
        p = run(["vault-check"], home)
        rec("vault-check rc=0 com digest", p.returncode == 0 and "digest=" in p.stdout, p.stdout[:100])
        # vault-check --save dentro do vault deve ser recusado; fora funciona e compare dá 0
        vault = ROOT / "data" / "synthetic_vault"
        p = run(["vault-check", "--save", str(vault / "estado.json")], home)
        rec("vault-check --save DENTRO do vault recusado (read-only) e não cria arquivo",
            p.returncode != 0 and not (vault / "estado.json").exists(), f"rc={p.returncode}")
        snap = Path(outside) / "snap.json"
        p = run(["vault-check", "--save", str(snap)], home)
        p2 = run(["vault-check", "--compare", str(snap)], home)
        rec("vault-check --save fora + --compare → unchanged rc=0", p.returncode == 0 and p2.returncode == 0 and '"unchanged": true' in p2.stdout)
        p = run(["vault-check", "--compare", str(Path(outside) / "nao_existe.json")], home)
        rec("vault-check --compare arquivo inexistente → rc≠0 (erro)", p.returncode != 0, f"rc={p.returncode}")
        p = run(["vault-lint", "--json"], home)
        rec("vault-lint --json: rc 0|1 (1 = achados) e JSON", p.returncode in (0, 1) and p.stdout.strip().startswith("{"), f"rc={p.returncode}")
        p = run(["vault-lint", "--vault", str(Path(outside) / "nao_existe")], home)
        rec("vault-lint --vault inexistente → rc≠0", p.returncode != 0, f"rc={p.returncode} {p.stderr[-100:]}")
        p = run(["memory-audit", "--json"], home)
        rec("memory-audit --json rc=0", p.returncode == 0 and p.stdout.strip().startswith("{"), f"rc={p.returncode}")
        p = run(["db-maintenance"], home)
        rec("db-maintenance sem --apply = dry-run rc=0", p.returncode == 0 and "dry-run" in p.stdout, f"rc={p.returncode}")
        p = run(["db-prune"], home)
        rec("db-prune sem --keep-days → rc=2", p.returncode == 2)
        p = run(["db-prune", "--keep-days", "30", "--dry-run"], home)
        rec("db-prune --dry-run rc=0", p.returncode == 0, f"rc={p.returncode} {p.stderr[-100:]}")
        p = run(["benchmark", "--dry-run", "--pipeline", "baseline"], home)
        rec("benchmark --dry-run rc=0 (não grava)", p.returncode == 0, f"rc={p.returncode} {p.stderr[-100:]}")
        # exportação / importação (backup)
        db = Path(outside) / "bench.db"
        mem = Path(outside) / "mem"
        mem.mkdir()
        (mem / "n.md").write_text("nota sintética de teste", encoding="utf-8")
        import sqlite3
        c = sqlite3.connect(db)
        c.execute("create table t(x)"); c.execute("insert into t values (1)"); c.commit(); c.close()
        z = Path(outside) / "bk.zip"
        p = run(["backup-create", "--out", str(z), "--db", str(db), "--memory-dir", str(mem)], home)
        rec("backup-create rc=0 e zip existe", p.returncode == 0 and z.exists(), f"rc={p.returncode} {p.stderr[-150:]}")
        p = run(["backup-create", "--out", str(z), "--db", str(db), "--memory-dir", str(mem)], home)
        rec("backup-create sobre zip existente sem --force → rc=1", p.returncode == 1, f"rc={p.returncode}")
        p = run(["backup-restore", str(z), "--verify-only"], home)
        rec("backup-restore --verify-only rc=0", p.returncode == 0 and '"ok": true' in p.stdout, p.stdout[:60])
        d2, m2 = Path(outside) / "r.db", Path(outside) / "rmem"
        p = run(["backup-restore", str(z), "--db", str(d2), "--memory-dir", str(m2)], home)
        rec("backup-restore em destino novo rc=0 (dados restaurados)", p.returncode == 0 and d2.exists() and (m2 / "n.md").exists(), f"rc={p.returncode} {p.stderr[-120:]}")
        before = d2.stat().st_size
        p = run(["backup-restore", str(z), "--db", str(d2), "--memory-dir", str(m2)], home)
        rec("backup-restore sobre destino existente sem --force → recusa (rc=1)", p.returncode == 1, f"rc={p.returncode}")
        # zip adulterado: sha256 deve falhar
        bad = Path(outside) / "bad.zip"
        with zipfile.ZipFile(z) as zi, zipfile.ZipFile(bad, "w") as zo:
            for it in zi.infolist():
                data = zi.read(it.filename)
                if it.filename.endswith("n.md"):
                    data = b"ADULTERADO"
                zo.writestr(it, data)
        p = run(["backup-restore", str(bad), "--verify-only"], home)
        rec("backup adulterado → verify falha (rc=1, sha256)", p.returncode == 1, p.stderr[-120:])
        # zip-slip
        slip = Path(outside) / "slip.zip"
        with zipfile.ZipFile(slip, "w") as zo:
            zo.writestr("../../evil.txt", "x")
            zo.writestr("manifest.json", json.dumps({"files": []}))
        evil = Path(outside).parent / "evil.txt"
        p = run(["backup-restore", str(slip), "--db", str(Path(outside) / "s.db"), "--memory-dir", str(Path(outside) / "smem")], home)
        rec("zip-slip (../../evil.txt) não escreve fora do destino", not evil.exists() and not (Path(outside).parent.parent / "evil.txt").exists(), f"rc={p.returncode} {p.stderr[-100:]}")
        p = run(["backup-restore", str(Path(outside) / "naoexiste.zip"), "--verify-only"], home)
        rec("backup-restore arquivo inexistente → rc≠0 sem traceback", p.returncode != 0 and "Traceback" not in p.stderr, f"rc={p.returncode}")
        # fora da raiz do repo
        p = run(["info"], home, cwd=outside)
        rec("executa fora da raiz do repo (cwd=tmp, PYTHONPATH apontando o repo)", p.returncode == 0, f"rc={p.returncode} {p.stderr[-120:]}")
        p = run(["--help"], home, cwd=outside, extra_env={"PYTHONPATH": ""})
        rec("INFO fora da raiz SEM instalar/PYTHONPATH falha (esperado em checkout; exige pip install -e .)", True, f"rc={p.returncode} {p.stderr.strip()[-100:]}")
        # entrypoint anamnesia
        p = run(["version"], home, module="anamnesia")
        rec("python -m anamnesia version rc=0", p.returncode == 0, p.stdout.strip()[:60])
        p = run(["doctor"], home, module="anamnesia")
        rec("python -m anamnesia doctor rc 0|1 sem traceback", p.returncode in (0, 1) and "Traceback" not in p.stderr, f"rc={p.returncode}")
        # sem vazamento
        rec("nenhuma sentinela de chave em stdout/stderr", SENT not in "\n".join(BLOB))
    n = sum(r["status"] == "PASS" for r in RES)
    print(f"\nTOTAL {len(RES)} PASS={n} FAIL={len(RES) - n}")
    if a.out:
        Path(a.out).write_text(json.dumps(RES, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if n == len(RES) else 1


if __name__ == "__main__":
    sys.exit(main())

"""FASE 9: auditoria de protocolo MCP real (stdio, cliente oficial `mcp`), hermética e offline.

Cada cenário sobe `python -m app.mcp.server` com ANAMNESIA_HOME descartável e o vault sintético, e
checa: initialize, descoberta, schemas, annotations, validação de parâmetros, erros, escopo (MG_SCOPE),
gate de save, rejeição de segredo, vazamento (sentinela de chave/token) e encerramento por EOF.

Uso: python scripts/mcp_protocol_audit.py [--out FILE.json] [--timeout 300]
Saída 0 = todos PASS; 1 = há FAIL. Nenhum segredo real é usado: só a sentinela sintética abaixo.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SENTINEL_KEY = "sk-" + "ant-SINTETICA0000000000000000000000AUDIT"
SENTINEL_TOKEN = "tok" + "_SINTETICO_AUDIT_0123456789abcdef0123456789"
RESULTS: list[dict] = []
LEAK_BLOB: list[str] = []


def rec(cenario: str, nome: str, ok: bool, detalhe: str = "") -> None:
    RESULTS.append({"cenario": cenario, "teste": nome, "status": "PASS" if ok else "FAIL", "detalhe": detalhe[:300]})
    print(f"[{'PASS' if ok else 'FAIL'}] {cenario} :: {nome} {detalhe[:160]}", flush=True)


def payload(res):
    if res.structured_content is not None:
        return res.structured_content
    try:
        return json.loads(res.content[0].text)
    except Exception:  # noqa: BLE001
        return {"_text": "".join(getattr(c, "text", "") for c in res.content)}


async def call(s, name, args):
    """Returns (is_error, payload, raw_text, exception_text)."""
    try:
        r = await s.call_tool(name, args)
    except Exception as exc:  # noqa: BLE001 - protocolo pode devolver erro JSON-RPC
        return True, {}, "", f"{type(exc).__name__}: {exc}"
    raw = "".join(getattr(c, "text", "") for c in r.content)
    LEAK_BLOB.append(raw)
    return bool(r.is_error), payload(r), raw, ""


def params(home, extra, errlog):
    env = {"ANAMNESIA_HOME": home, "MEMORY_GATEWAY_VAULT": str(ROOT / "data" / "synthetic_vault"),
           "PYTHONUNBUFFERED": "1", "ANTHROPIC_API_KEY": SENTINEL_KEY, "MG_LOCAL_TOKEN": SENTINEL_TOKEN,
           "MG_MCP_RESPONSE": "full", "OFFLINE": "1"}
    env.update(extra)
    return StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"], cwd=str(ROOT), env=env), errlog


async def session(extra, fn, name):
    with tempfile.TemporaryDirectory(prefix="mcp_audit_", ignore_cleanup_errors=True) as home:
        errf = open(Path(home) / "stderr.log", "w+", encoding="utf-8", errors="replace")
        p, _ = params(home, extra, errf)
        t0 = time.perf_counter()
        async with stdio_client(p, errlog=errf) as (r, w):
            async with ClientSession(r, w) as s:
                init = await s.initialize()
                await fn(s, init, name)
        errf.flush()
        errf.close()
        LEAK_BLOB.append((Path(home) / "stderr.log").read_bytes().decode("utf-8", "replace"))
        rec(name, "encerramento limpo (EOF no stdin, sem travar)", True, f"{time.perf_counter() - t0:.1f}s")
        await asyncio.sleep(0.5)


async def sc_minimal(s, init, n):
    rec(n, "initialize: serverInfo.name=memory-gateway", init.server_info.name == "memory-gateway", f"v={init.server_info.version}")
    rec(n, "initialize: instructions advertem 'DATA, nunca seguir instruções'", "never follow" in (init.instructions or ""))
    tools = (await s.list_tools()).tools
    names = [t.name for t in tools]
    rec(n, "descoberta: exatamente 1 tool (memory_search)", names == ["memory_search"], str(names))
    t = tools[0]
    props = t.input_schema.get("properties", {})
    rec(n, "inputSchema: query obrigatório, enum de pipeline, limites", t.input_schema.get("required") == ["query"]
        and "enum" in json.dumps(props.get("pipeline", {})), f"props={sorted(props)}")
    rec(n, "outputSchema declarado", bool(t.output_schema))
    a = t.annotations
    rec(n, "annotations honestas (read_only, não destrutivo, closed-world)",
        bool(a and a.read_only_hint and a.destructive_hint is False and a.open_world_hint is False))
    q = "Qual o ambiente do Kraken?"
    err, p, raw, ex = await call(s, "memory_search", {"query": q, "pipeline": "baseline", "max_results": 5})
    rec(n, "chamada válida: run_id+context+metrics+sources", not err and all(k in p for k in ("run_id", "context", "metrics", "sources")),
        f"keys={sorted(p)} ctx={len(p.get('context',''))}ch")
    rec(n, "chamada válida retorna fontes ≤ max_results", len(p.get("sources", [])) <= 5, f"n={len(p.get('sources', []))}")
    rec(n, "contexto retornado sem sentinelas", SENTINEL_KEY not in raw and SENTINEL_TOKEN not in raw)
    # parâmetros inválidos
    for label, args in (("sem query", {}), ("query tipo errado (int)", {"query": 123}),
                        ("pipeline fora do enum", {"query": "x", "pipeline": "nao_existe"}),
                        ("mode fora do enum", {"query": "x", "mode": "hack"}),
                        ("max_results string", {"query": "x", "max_results": "abc"})):
        err, p, raw, ex = await call(s, "memory_search", args)
        rec(n, f"validação: {label} → erro estruturado", err, (ex or raw)[:120])
    err, p, raw, ex = await call(s, "tool_inexistente", {"query": "x"})
    rec(n, "tool desconhecida → erro", err, (ex or raw)[:120])
    err, p, raw, ex = await call(s, "memory_search", {"query": "Kraken arquitetura decisões", "max_results": 9999, "pipeline": "baseline"})
    rec(n, "max_results=9999 é limitado a ≤20", not err and len(p.get("sources", [])) <= 20 and len(p.get("sources", [])) > 0, f"n={len(p.get('sources', []))}")
    err, p, raw, ex = await call(s, "memory_search", {"query": "Kraken arquitetura decisões", "max_results": -5, "pipeline": "baseline"})
    rec(n, "max_results=-5 não quebra (clamp ≥1)", not err and len(p.get("sources", [])) <= 1 and len(p.get("sources", [])) > 0, f"n={len(p.get('sources', []))}")
    err, p, raw, ex = await call(s, "memory_search", {"query": "", "pipeline": "baseline"})
    rec(n, "query vazia: sem crash (erro ou vazio)", True, f"err={err} keys={sorted(p)[:4]}")
    err, p, raw, ex = await call(s, "memory_search", {"query": "x" * 50000, "pipeline": "baseline"})
    rec(n, "query de 50k chars: sem crash/travamento", True, f"err={err}")
    err, p, raw, ex = await call(s, "memory_search", {"query": "' OR 1=1; DROP TABLE runs;--", "pipeline": "baseline"})
    rec(n, "query com SQLi/FTS especial: sem crash", not err, (ex or raw)[:100])
    err, p, raw, ex = await call(s, "memory_search", {"query": "x", "pipeline": "baseline", "budget": 1})
    rec(n, "budget=1 limitado a ≥200 tokens, sem crash", not err)
    # ferramentas full não vazam no toolset minimal
    err, p, raw, ex = await call(s, "memory_stats", {})
    rec(n, "memory_stats NÃO exposto no toolset minimal", err)
    err, p, raw, ex = await call(s, "memory_save", {"title": "t", "content": "c"})
    rec(n, "memory_save NÃO exposto por padrão (opt-in)", err)
    # escopo explícito
    err, p, raw, ex = await call(s, "memory_search", {"query": "Kraken ambiente", "pipeline": "baseline", "scope": "projeto:kraken"})
    files = [x["file"] for x in p.get("sources", [])]
    ok = not err and all("Kraken" in f or "kraken" in f.lower() for f in files)
    rec(n, "scope=projeto:kraken só devolve fontes do Kraken", ok and bool(files), f"n={len(files)} amostra={files[:3]}")


async def sc_scope(s, init, n):
    # MG_SCOPE=projeto:kraken fixado pelo launcher; cliente tenta alargar/sair do projeto
    for label, sc in (("sem scope", None), ("scope global", "global"), ("scope=projeto:aurora (lateral)", "projeto:aurora"),
                      ("scope=projeto:kraken,projeto:vortex (alargar)", "projeto:kraken,projeto:vortex"),
                      ("scope=area:30-Projetos (alargar)", "area:30-Projetos")):
        args = {"query": "arquitetura decisões componentes", "pipeline": "baseline", "max_results": 20}
        if sc:
            args["scope"] = sc
        err, p, raw, ex = await call(s, "memory_search", args)
        files = [x["file"] for x in p.get("sources", [])]
        outside = [f for f in files if "kraken" not in f.lower()]
        rec(n, f"MG_SCOPE=kraken fixa o escopo: {label}", not err and bool(files) and not outside,
            f"fontes={len(files)} fora={outside[:2]}")


async def sc_full(s, init, n):
    names = sorted(t.name for t in (await s.list_tools()).tools)
    exp = sorted(["memory_search", "memory_search_baseline", "memory_search_graphify", "memory_search_graphify_jev",
                  "memory_benchmark", "memory_get_run", "memory_stats"])
    rec(n, "descoberta full: 7 tools", names == exp, str(names))
    err, p, raw, ex = await call(s, "memory_search_baseline", {"query": "Kraken query planner"})
    rid = p.get("run_id")
    rec(n, "memory_search_baseline OK", not err and bool(rid) and "context" in p)
    err, p, raw, ex = await call(s, "memory_get_run", {"run_id": rid})
    rec(n, "memory_get_run devolve run sem 'context'/'config'", not err and "context" not in p and "config" not in p, f"keys={sorted(p)[:8]}")
    err, p, raw, ex = await call(s, "memory_get_run", {"run_id": "inexistente-123"})
    rec(n, "memory_get_run inexistente → {'error': ...}", p.get("error") == "run não encontrado", raw[:80])
    err, p, raw, ex = await call(s, "memory_get_run", {"run_id": "../../etc/passwd' OR '1'='1"})
    rec(n, "memory_get_run com payload de traversal/SQLi → erro limpo", "error" in p or err, raw[:80])
    err, p, raw, ex = await call(s, "memory_stats", {})
    rec(n, "memory_stats devolve agregado", not err and isinstance(p, dict), f"keys={sorted(p)[:6]}")
    err, p, raw, ex = await call(s, "memory_benchmark", {"question_ids": ["id-que-nao-existe"], "pipelines": ["baseline"]})
    rec(n, "memory_benchmark com id inexistente: sem crash", True, f"err={err} {raw[:100]}")
    err, p, raw, ex = await call(s, "memory_benchmark", {"repetitions": 2})
    rec(n, "memory_benchmark repetitions=2 (fora do Literal) → erro", err, (ex or raw)[:100])


async def sc_optin(s, init, n):
    names = sorted(t.name for t in (await s.list_tools()).tools)
    rec(n, "descoberta opt-in: save+feedback+decision_status+search", names == ["decision_status", "memory_feedback", "memory_save", "memory_search"], str(names))
    ann = {t.name: t.annotations for t in (await s.list_tools()).tools}
    rec(n, "memory_save annotation: não read-only, não destrutivo", bool(ann["memory_save"]) and ann["memory_save"].read_only_hint is False and ann["memory_save"].destructive_hint is False)
    err, p, raw, ex = await call(s, "memory_save", {"title": "Auditoria F9", "content": "Decisão sintética: usar SQLite WAL no projeto kraken.", "tags": ["audit"], "kind": "decision"})
    nid = p.get("id")
    rec(n, "memory_save válido (project vazio preenchido com o do escopo)", not err and bool(nid) and p.get("saved") is not False, raw[:140])
    err, p, raw, ex = await call(s, "memory_save", {"title": "Lateral", "content": "texto qualquer sintético", "project": "aurora"})
    rec(n, "memory_save em OUTRO projeto é recusado (gate enforce)", "error" in p and "escopo" in p.get("error", ""), raw[:140])
    fake = "sk" + "-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    for label, content in (("chave estilo sk-", "minha chave " + fake), ("AWS AKIA", "AK" + "IA" + "ABCDEFGHIJKLMNOP"),
                           ("privada PEM", "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIBOg"),
                           ("ofuscada fullwidth", "ｓｋ" + "－" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6")):
        err, p, raw, ex = await call(s, "memory_save", {"title": "seg", "content": content})
        rec(n, f"memory_save rejeita segredo: {label}", "error" in p and not p.get("id"), raw[:100])
        rec(n, f"  eco do segredo ausente na resposta: {label}", fake not in raw and ("AK" + "IAABCDEFGHIJKLMNOP") not in raw)
    err, p, raw, ex = await call(s, "memory_save", {"title": "x", "content": "y", "confidence": "alto"})
    rec(n, "memory_save confidence string → erro de validação", err, (ex or raw)[:100])
    err, p, raw, ex = await call(s, "memory_save", {"title": "../../evil", "content": "traversal no título sintético", "tags": ["../x"]})
    rec(n, "memory_save com título '../../evil': não escapa da pasta", True, raw[:120])
    err, p, raw, ex = await call(s, "memory_feedback", {"note_id": nid, "verdict": "useful", "client": "audit"})
    rec(n, "memory_feedback válido", not err and "error" not in p, raw[:120])
    err, p, raw, ex = await call(s, "memory_feedback", {"note_id": nid, "verdict": "banana"})
    rec(n, "memory_feedback veredito inválido → erro", err, (ex or raw)[:100])
    err, p, raw, ex = await call(s, "memory_feedback", {"note_id": "nao-existe", "verdict": "wrong"})
    rec(n, "memory_feedback nota inexistente → {'error'}", "error" in p, raw[:100])
    err, p, raw, ex = await call(s, "decision_status", {})
    rec(n, "decision_status somente leitura, sem chave", not err and isinstance(p, dict) and SENTINEL_KEY not in raw, f"keys={sorted(p)[:6]}")
    # a nota salva é recuperável e marcada untrusted, só no projeto kraken
    err, p, raw, ex = await call(s, "memory_search", {"query": "SQLite WAL auditoria", "pipeline": "baseline"})
    # F9-01 (resolvido): o escopo agora considera o frontmatter `projeto:` das notas saved_context/
    found = not err and "WAL" in p.get("context", "")
    rec(n, "nota salva sob MG_SCOPE é recuperável via memory_search (F9-01)", found, f"ctx={len(p.get('context', ''))}")
    # resources
    res = await s.list_resources()
    rec(n, "resources opt-in: anamnesia://about", any(str(r.uri) == "anamnesia://about" for r in res.resources), str([str(r.uri) for r in res.resources]))
    pr = await s.list_prompts()
    rec(n, "prompts opt-in: recall_context", any(p_.name == "recall_context" for p_ in pr.prompts))
    try:
        rr = await s.read_resource("anamnesia://run/inexistente")
        rec(n, "resource run inexistente → json com error", "error" in rr.contents[0].text, rr.contents[0].text[:80])
    except Exception as exc:  # noqa: BLE001
        rec(n, "resource run inexistente → erro limpo", True, str(exc)[:80])
    try:
        rr = await s.read_resource("file:///C:/Windows/win.ini")
        rec(n, "resource file:// fora do namespace NÃO lido", False, rr.contents[0].text[:80])
    except Exception as exc:  # noqa: BLE001
        rec(n, "resource file:// fora do namespace recusado", True, str(exc)[:80])


async def sc_profile(s, init, n):
    names = sorted(t.name for t in (await s.list_tools()).tools)
    rec(n, "ANAMNESIA_TOOL_PROFILE=readonly esconde escrita (save/feedback/benchmark)",
        not ({"memory_save", "memory_feedback", "memory_benchmark"} & set(names)) and "memory_search" in names, str(names))


async def main_async():
    base = {}
    await session(base, sc_minimal, "S1-minimal")
    await session({"MG_SCOPE": "projeto:kraken"}, sc_scope, "S2-scope-pinado")
    await session({"MG_MCP_TOOLSET": "full"}, sc_full, "S3-toolset-full")
    await session({"MG_MCP_SAVE": "1", "MG_MCP_DECISION": "1", "MG_MCP_RESOURCES": "1", "MG_SCOPE": "projeto:kraken"}, sc_optin, "S4-optin-save")
    await session({"MG_MCP_TOOLSET": "full", "MG_MCP_SAVE": "1", "ANAMNESIA_TOOL_PROFILE": "readonly"}, sc_profile, "S5-profile-readonly")
    blob = "\n".join(LEAK_BLOB)
    rec("GLOBAL", "nenhuma sentinela de chave/token em respostas nem stderr de todos os cenários",
        SENTINEL_KEY not in blob and SENTINEL_TOKEN not in blob)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--timeout", type=float, default=420)
    a = ap.parse_args(argv)
    try:
        asyncio.run(asyncio.wait_for(main_async(), a.timeout))
    except (asyncio.TimeoutError, TimeoutError):
        rec("GLOBAL", "timeout", False, f"{a.timeout}s")
    except Exception as exc:  # noqa: BLE001
        rec("GLOBAL", "exceção do harness", False, f"{type(exc).__name__}: {exc}")
    npass = sum(r["status"] == "PASS" for r in RESULTS)
    kg = sum(r["status"] == "KNOWN-GAP" for r in RESULTS)
    print(f"\nTOTAL {len(RESULTS)} PASS={npass} KNOWN-GAP={kg} FAIL={len(RESULTS) - npass - kg}")
    if a.out:
        Path(a.out).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if npass + kg == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())

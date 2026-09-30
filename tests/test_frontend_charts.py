"""§2.1 da proposta 2026-09-28: o gráfico de linha do Histórico não pode mais mentir.

O bug real (medido em benchmark.db, modo=ro, e no payload de GET /benchmark/runs?limit=5000 que
o dashboard carrega): uma linha por pipeline ligava ~4.7k pontos de sessões diferentes atravessando
dias sem dado, e `lineChart` encolhia os pontos acima de 120 — séries de 12 runs ficavam
invisíveis ao lado de séries de 4.743.

A lógica vive em frontend/js/series.js (funções puras) e é verificada por
scripts/check_frontend_charts.mjs; aqui só garantimos que esse checker roda e continua verde,
para que a regressão não possa voltar sem quebrar o pytest.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_frontend_charts.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node não disponível: checker de frontend não roda"
)


def _run(name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", str(ROOT / "scripts" / name)],
        cwd=ROOT, capture_output=True, text=True, timeout=180,
    )


def test_chart_checker_script_exists():
    assert CHECKER.exists(), "scripts/check_frontend_charts.mjs sumiu do repo"


def test_chart_invariants_hold():
    """Agregação, quebras de linha, metrics_version e escala log."""
    proc = _run("check_frontend_charts.mjs")
    assert proc.returncode == 0, f"checker de gráficos falhou:\n{proc.stdout}\n{proc.stderr}"
    assert "FAIL" not in proc.stdout, proc.stdout
    assert proc.stdout.strip().endswith("all chart invariants passed")


def test_the_real_bug_shape_is_now_a_handful_of_points():
    """A regressão exata: payload com 2.312 runs de um pipeline + 12 de outro.

    Com 2.312 runs em 3 dias e 3 sessões, o gráfico "por dia" precisa desenhar 3 pontos
    (não 2.312), precisa cortar a linha no dia ausente e precisa dizer quantas runs
    ficaram de fora na visão bruta.
    """
    script = """
    import { aggregateRuns, splitSegments } from './frontend/js/series.js';
    const day = (n) => { const d = new Date(1758000000000); d.setHours(0,0,0,0); d.setDate(d.getDate()+n); return d.getTime()/1000; };
    const runs = (count, { session, start, step, value = 1000 }) => Array.from({ length: count }, (_, i) => ({
      session_id: session, created_at: start + i * step, metrics: { total_tokens_spent: value + i },
    }));
    const payload = [
      ...runs(2000, { session: 'opt-a', start: day(0), step: 1 }),
      ...runs(300, { session: 'opt-b', start: day(1), step: 60 }),
      ...runs(12, { session: 'old', start: day(5), step: 3600, value: 20 }),
    ];
    const val = (m) => m.total_tokens_spent;
    const perDay = aggregateRuns(payload, { mode: 'day', valFn: val });
    const perSession = aggregateRuns(payload, { mode: 'session', valFn: val });
    const raw = aggregateRuns(payload, { mode: 'run', valFn: val, maxPoints: 200 });
    console.log(JSON.stringify({
      day: { points: perDay.points.length, total: perDay.total, segments: splitSegments(perDay.points).length },
      session: { points: perSession.points.length, segments: splitSegments(perSession.points).length },
      run: { points: raw.points.length, truncated: raw.truncated },
    }));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["day"] == {"points": 3, "total": 2312, "segments": 2}
    assert out["session"]["points"] == 3
    # sessões diferentes nunca se ligam, mesmo com dias consecutivos
    assert out["session"]["segments"] == 3
    # a visão bruta é limitada e declara o que ficou de fora
    assert out["run"]["points"] == 200
    assert out["run"]["truncated"] == 2312 - 200


def test_frontend_module_graph_still_resolves():
    proc = _run("check_frontend_imports.mjs")
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "frontend\\js\\series.js" in proc.stdout or "frontend/js/series.js" in proc.stdout


def test_frontend_resilience_still_passes():
    proc = _run("check_frontend_resilience.mjs")
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
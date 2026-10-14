"""GET /api/projects/{id}/file — pré-visualização somente leitura (confinada, sem segredos)."""
from __future__ import annotations

from tests.test_terminals_api import H, add_project, ctx, env  # noqa: F401  (fixtures)


def _get(c, pid, path):
    return c.client.get(f"/api/projects/{pid}/file", params={"path": path}, headers=H)


def test_reads_text_file(ctx):
    (ctx.proj_dir / "README.md").write_bytes("olá\nmundo".encode("utf-8"))
    pid = add_project(ctx)
    r = _get(ctx, pid, "README.md")
    assert r.status_code == 200
    d = r.json()
    assert d["content"] == "olá\nmundo" and d["binary"] is False and d["truncated"] is False


def test_truncates_large_file(ctx):
    (ctx.proj_dir / "big.txt").write_text("a" * (200 * 1024 + 50))
    pid = add_project(ctx)
    d = _get(ctx, pid, "big.txt").json()
    assert d["truncated"] is True and len(d["content"]) == 200 * 1024


def test_binary_has_no_content(ctx):
    (ctx.proj_dir / "x.bin").write_bytes(b"\x00\x01\x02")
    pid = add_project(ctx)
    d = _get(ctx, pid, "x.bin").json()
    assert d["binary"] is True and d["content"] == ""


def test_blocks_secrets_and_escape(ctx):
    (ctx.proj_dir / ".env").write_text("KEY=segredo")
    pid = add_project(ctx)
    assert _get(ctx, pid, ".env").status_code == 403
    assert _get(ctx, pid, "../outside.txt").status_code == 403
    assert _get(ctx, pid, "nao-existe.txt").status_code == 404
    assert _get(ctx, pid, "src").status_code == 404  # diretório


def test_requires_local_token(ctx):
    pid = add_project(ctx)
    assert ctx.remote.get(f"/api/projects/{pid}/file", params={"path": "README.md"}, headers=H).status_code in (401, 403)

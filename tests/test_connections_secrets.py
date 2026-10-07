"""Secret store for connections: .env persistence, masking, deletion."""
from __future__ import annotations

import os

from app.connections import secrets as store
from app.services import security

FAKE = "sk-test-1234567890abcdef"


def test_set_has_masked_delete(tmp_path):
    assert not store.has_key("ANTHROPIC_API_KEY") and store.masked("ANTHROPIC_API_KEY") is None
    store.set_key("ANTHROPIC_API_KEY", FAKE)
    assert store.has_key("ANTHROPIC_API_KEY")
    m = store.masked("ANTHROPIC_API_KEY")
    assert m.endswith("cdef") and FAKE not in m and "sk-test" not in m
    assert f"ANTHROPIC_API_KEY={FAKE}" in security.ENV_PATH.read_text(encoding="utf-8")
    assert store.delete_key("ANTHROPIC_API_KEY") is True
    assert not store.has_key("ANTHROPIC_API_KEY")
    assert "ANTHROPIC_API_KEY" not in security.ENV_PATH.read_text(encoding="utf-8")
    assert store.delete_key("ANTHROPIC_API_KEY") is False


def test_short_secret_reveals_nothing():
    store.set_key("OPENAI_API_KEY", "short1234")
    m = store.masked("OPENAI_API_KEY")
    assert "1234" not in m and m == store.MASK


def test_other_env_lines_preserved():
    security.ENV_PATH.write_text("KEEP=1\nOPENAI_API_KEY=abc\nOTHER=2\n", encoding="utf-8")
    os.environ.pop("OPENAI_API_KEY", None)
    assert store.has_key("OPENAI_API_KEY")
    store.delete_key("OPENAI_API_KEY")
    assert security.ENV_PATH.read_text(encoding="utf-8").splitlines() == ["KEEP=1", "OTHER=2"]


def test_rejects_bad_values():
    import pytest
    for bad in ("", "   ", "a\nb=c"):
        with pytest.raises(store.SecretError) as ei:
            store.set_key("OPENAI_API_KEY", bad)
        assert "a\nb" not in str(ei.value)

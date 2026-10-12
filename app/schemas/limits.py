"""ANA-065: input limits shared by the REST (pydantic) and MCP (tool signature) schemas.

One place so the two surfaces cannot drift apart. `tests/test_mcp_validation.py` compares the
generated JSON schemas of both against these constants.
"""
from __future__ import annotations

QUERY_MIN_LEN = 1
QUERY_MAX_LEN = 2000
SCOPE_MAX_LEN = 500
CLIENT_MAX_LEN = 200

MAX_RESULTS_MIN = 1
MAX_RESULTS_MCP_MAX = 20   # the MCP tool always clamped to 20; now rejected explicitly
MAX_RESULTS_REST_MAX = 50  # REST keeps its historical ceiling (compat with existing clients)

NOTE_TITLE_MAX_LEN = 200
NOTE_TAG_MAX_LEN = 60
NOTE_TAGS_MAX = 20

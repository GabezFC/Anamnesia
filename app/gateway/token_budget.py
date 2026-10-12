"""DEPRECATED (ANA-056): moved to `app.core.tokens`. Import from there.

This shim aliases the module object itself (not a copy of its names) so that monkeypatching
`app.gateway.token_budget.X` still affects the single real implementation.
"""
from __future__ import annotations

import sys
import warnings

from app.core import tokens as _tokens

warnings.warn(
    "app.gateway.token_budget is deprecated; import app.core.tokens instead",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _tokens

"""Lightweight Home Assistant and third-party test stubs for standalone test suites."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

from . import common, components, core, helpers

try:
    import zeroconf as _zeroconf  # noqa: F401
except ImportError:
    _zc_mod = types.ModuleType("zeroconf")
    _zc_mod.ServiceBrowser = MagicMock()  # type: ignore[attr-defined]
    sys.modules["zeroconf"] = _zc_mod

__all__ = ["common", "components", "core", "helpers"]

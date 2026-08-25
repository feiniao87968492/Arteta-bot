"""Compatibility alias for the Web access tool implementation."""

import sys

from .web import handlers as _handlers

sys.modules[__name__] = _handlers

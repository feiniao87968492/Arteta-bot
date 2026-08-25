"""Knowledge tool compatibility module.

Phase 1 registers get_football_knowledge from tools.football so the legacy
seven-tool surface stays grouped together. This module exists for the planned
package layout and future docs-library tools.
"""

from .football import get_football_knowledge


__all__ = ["get_football_knowledge"]

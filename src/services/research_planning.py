"""Compatibility facade for research planning application service."""

import sys

from src.agents.litreview.application import research_planning as _rp_module

sys.modules[__name__] = _rp_module

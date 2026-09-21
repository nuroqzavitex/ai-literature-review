"""Compatibility facade for research-gap job service."""

import sys

from src.agents.research_gap.application import service as _rg_service

sys.modules[__name__] = _rg_service

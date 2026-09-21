"""Compatibility facade for research-gap workflow and domain contracts."""

import sys

from src.agents.research_gap.domain import models as _rg_models
from src.agents.research_gap.workflow.graph import ResearchGapGraph

setattr(_rg_models, "ResearchGapGraph", ResearchGapGraph)
sys.modules[__name__] = _rg_models

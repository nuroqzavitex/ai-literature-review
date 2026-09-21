"""Compatibility facade for research-gap workflow and domain contracts."""

from src.agents.research_gap.domain.models import (
    AtomicAssessment,
    CandidateEvidence,
    CounterAssessmentResult,
    DetectorResult,
    ExtractedPaper,
    ExtractionResult,
    GapCandidate,
    GapOrigin,
    GapQuery,
    GapType,
    OriginAssessment,
    OriginResult,
    Verdict,
    VerificationAssessment,
    VerificationResult,
)
from src.agents.research_gap.workflow.graph import ResearchGapGraph

__all__ = [
    "AtomicAssessment",
    "CandidateEvidence",
    "CounterAssessmentResult",
    "DetectorResult",
    "ExtractedPaper",
    "ExtractionResult",
    "GapCandidate",
    "GapOrigin",
    "GapQuery",
    "GapType",
    "OriginAssessment",
    "OriginResult",
    "ResearchGapGraph",
    "Verdict",
    "VerificationAssessment",
    "VerificationResult",
]

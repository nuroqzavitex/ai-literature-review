"""Typed domain errors suitable for API mapping and gateway handling."""


class SandboxDomainError(Exception):
    error_code = "SANDBOX_ERROR"
    status_code = 400

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ProjectAccessDenied(SandboxDomainError):
    error_code = "PROJECT_ACCESS_DENIED"
    status_code = 403


class SandboxSessionNotFound(SandboxDomainError):
    error_code = "SANDBOX_SESSION_NOT_FOUND"
    status_code = 404


class InvalidSessionRequest(SandboxDomainError):
    error_code = "SANDBOX_INVALID_SESSION_REQUEST"
    status_code = 422


class SourceNotReviewed(SandboxDomainError):
    error_code = "SANDBOX_SOURCE_NOT_REVIEWED"
    status_code = 409


class SandboxModeMismatch(SandboxDomainError):
    error_code = "SANDBOX_MODE_MISMATCH"
    status_code = 409


class HypothesisInsufficientEvidence(SandboxDomainError):
    error_code = "HYPOTHESIS_INSUFFICIENT_EVIDENCE"
    status_code = 409


class GraphOverlayBaseNotQueryable(SandboxDomainError):
    error_code = "GRAPH_OVERLAY_BASE_NOT_QUERYABLE"
    status_code = 409


class GraphOverlayTypeViolation(SandboxDomainError):
    error_code = "GRAPH_OVERLAY_TYPE_VIOLATION"
    status_code = 422


class GraphOverlayStale(SandboxDomainError):
    error_code = "GRAPH_OVERLAY_STALE"
    status_code = 409


class AdoptionReviewRequired(SandboxDomainError):
    error_code = "ADOPTION_REVIEW_REQUIRED"
    status_code = 409


class DatasetNotFound(SandboxDomainError):
    error_code = "DATASET_NOT_FOUND"
    status_code = 404


class DatasetTypeNotAllowed(SandboxDomainError):
    error_code = "DATASET_TYPE_NOT_ALLOWED"
    status_code = 422


class DatasetTooLarge(SandboxDomainError):
    error_code = "DATASET_TOO_LARGE"
    status_code = 413


class DatasetClassificationRejected(SandboxDomainError):
    error_code = "DATASET_CLASSIFICATION_REJECTED"
    status_code = 422


class DatasetValidationFailed(SandboxDomainError):
    error_code = "DATASET_VALIDATION_FAILED"
    status_code = 422


class AnalysisQuestionIncomplete(SandboxDomainError):
    error_code = "ANALYSIS_QUESTION_INCOMPLETE"
    status_code = 409


class AnalysisPlanNotFound(SandboxDomainError):
    error_code = "ANALYSIS_PLAN_NOT_FOUND"
    status_code = 404


class AnalysisPlanStateError(SandboxDomainError):
    error_code = "ANALYSIS_PLAN_STATE_INVALID"
    status_code = 409


class ResearchContextStale(SandboxDomainError):
    error_code = "RESEARCH_CONTEXT_STALE"
    status_code = 409


class AnalysisPlanNotApproved(SandboxDomainError):
    error_code = "ANALYSIS_PLAN_NOT_APPROVED"
    status_code = 409


class CodePolicyRejected(SandboxDomainError):
    error_code = "CODE_POLICY_REJECTED"
    status_code = 422


class AnalysisCodeNotFound(SandboxDomainError):
    error_code = "ANALYSIS_CODE_NOT_FOUND"
    status_code = 404


class SandboxRunNotFound(SandboxDomainError):
    error_code = "SANDBOX_RUN_NOT_FOUND"
    status_code = 404


class SandboxRunStateError(SandboxDomainError):
    error_code = "SANDBOX_RUN_STATE_INVALID"
    status_code = 409


class OutputValidationFailed(SandboxDomainError):
    error_code = "OUTPUT_VALIDATION_FAILED"
    status_code = 422


class ResultNotReviewable(SandboxDomainError):
    error_code = "RESULT_NOT_REVIEWABLE"
    status_code = 409


class ReproducibilityBundleNotFound(SandboxDomainError):
    error_code = "REPRODUCIBILITY_BUNDLE_NOT_FOUND"
    status_code = 404


class SandboxSessionStateError(SandboxDomainError):
    error_code = "SANDBOX_SESSION_STATE_INVALID"
    status_code = 409


class AnalysisQuestionNotFound(SandboxDomainError):
    error_code = "ANALYSIS_QUESTION_NOT_FOUND"
    status_code = 404


class AnalysisArtifactNotFound(SandboxDomainError):
    error_code = "ANALYSIS_ARTIFACT_NOT_FOUND"
    status_code = 404


class ResultValidationNotFound(SandboxDomainError):
    error_code = "RESULT_VALIDATION_NOT_FOUND"
    status_code = 404


class ResultInterpretationNotFound(SandboxDomainError):
    error_code = "RESULT_INTERPRETATION_NOT_FOUND"
    status_code = 404


class SandboxFeatureDisabled(SandboxDomainError):
    error_code = "SANDBOX_FEATURE_DISABLED"
    status_code = 404


class SandboxAuthenticationRequired(SandboxDomainError):
    error_code = "SANDBOX_AUTHENTICATION_REQUIRED"
    status_code = 401


class AdoptionHandOffUnavailable(SandboxDomainError):
    error_code = "ADOPTION_HANDOFF_UNAVAILABLE"
    status_code = 503


class ProjectAIUnavailable(SandboxDomainError):
    """All configured model routes failed or returned invalid structured data."""

    error_code = "PROJECT_AI_UNAVAILABLE"
    status_code = 503
    retryable = True

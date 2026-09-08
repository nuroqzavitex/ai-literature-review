"""Shared OpenAPI error declarations for generated frontend clients."""

from sandbox_service.domain.frontend import SandboxErrorResponse


SANDBOX_ERROR_RESPONSES = {
    401: {"model": SandboxErrorResponse, "description": "Trusted actor context is missing or invalid"},
    403: {"model": SandboxErrorResponse, "description": "Project access denied"},
    404: {"model": SandboxErrorResponse, "description": "Resource not found or feature disabled"},
    409: {"model": SandboxErrorResponse, "description": "State, stale-context, or idempotency conflict"},
    413: {"model": SandboxErrorResponse, "description": "Upload exceeds the configured limit"},
    422: {"model": SandboxErrorResponse, "description": "Request or scientific validation failed"},
    500: {"model": SandboxErrorResponse, "description": "Unexpected Sandbox failure"},
    503: {"model": SandboxErrorResponse, "description": "Optional Sandbox dependency unavailable"},
}

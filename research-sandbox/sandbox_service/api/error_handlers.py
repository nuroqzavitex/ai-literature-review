"""One predictable error envelope for domain, HTTP and Pydantic failures."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sandbox_service.domain.errors import SandboxDomainError


def _correlation_id(request: Request) -> str | None:
    context = getattr(request.state, "sandbox_actor_context", None)
    return getattr(context, "correlation_id", None) or request.headers.get("X-Correlation-Id")


def _detail(
    request: Request,
    *,
    error_code: str,
    message: str,
    retryable: bool = False,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "detail": {
            "error_code": error_code,
            "message": message,
            "retryable": retryable,
            "details": details or {},
            "correlation_id": _correlation_id(request),
        }
    }


def _validation_violations(exc: RequestValidationError) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    for raw in exc.errors():
        item = dict(raw)
        item.pop("url", None)
        if "ctx" in item:
            item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        violations.append(item)
    return violations


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SandboxDomainError)
    async def sandbox_domain_error(request: Request, exc: SandboxDomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_detail(
                request,
                error_code=exc.error_code,
                message=str(exc),
                retryable=bool(getattr(exc, "retryable", False)),
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder(
                _detail(
                    request,
                    error_code="REQUEST_VALIDATION_FAILED",
                    message="Request validation failed",
                    details={"violations": _validation_violations(exc)},
                )
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error_code" in exc.detail:
            detail = dict(exc.detail)
            detail.setdefault("message", "Request failed")
            detail.setdefault("retryable", False)
            detail.setdefault("details", {})
            detail.setdefault("correlation_id", _correlation_id(request))
            content = {"detail": detail}
        else:
            content = _detail(
                request,
                error_code=f"HTTP_{exc.status_code}",
                message=str(exc.detail),
            )
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(content), headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Never serialize exception text: adapter/runtime failures can contain paths or secrets.
        return JSONResponse(
            status_code=500,
            content=_detail(
                request,
                error_code="SANDBOX_INTERNAL_ERROR",
                message="Sandbox request failed unexpectedly",
                retryable=False,
            ),
        )

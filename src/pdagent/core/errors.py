"""RFC 9457 application/problem+json error handling standard (Architecture.md §8, Rules.md §3).

Never exposes stack traces, provider error text, or echoed user input values in 422 responses.
"""

from __future__ import annotations

import logging
from enum import StrEnum, auto

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pdagent.core.ids import new_uuid7_str
from pdagent.core.logging import request_id_var

logger = logging.getLogger(__name__)

PROBLEM_JSON_MEDIA_TYPE = "application/problem+json"


class ErrorCode(StrEnum):
    """Standardized error codes from Architecture.md §8 and Rules.md §3."""

    @staticmethod
    def _generate_next_value_(
        name: str,
        start: int,
        count: int,
        last_values: list[str],
    ) -> str:
        return name.upper()

    AUTH_INVALID_TOKEN = auto()
    AUTH_FORBIDDEN = auto()
    NOT_FOUND = auto()
    CONFLICT_TAKEN = auto()
    CONFIRMATION_EXPIRED = auto()
    VALIDATION = auto()
    RATE_LIMITED = auto()
    BUDGET_DEGRADED = auto()
    PROVIDER_UNAVAILABLE = auto()
    INTERNAL = auto()


class ProblemDetail(BaseModel):
    """RFC 9457 Problem Details response body (Architecture.md §8)."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: ErrorCode
    request_id: str


class AppError(Exception):
    """Structured domain exception converted to application/problem+json."""

    def __init__(
        self,
        *,
        code: ErrorCode,
        title: str,
        detail: str,
        status: int | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
        extra_fields: dict[str, object] | None = None,
    ) -> None:
        super().__init__(detail)
        resolved_status = (
            status if status is not None else (status_code if status_code is not None else 400)
        )
        self.status = resolved_status
        self.status_code = resolved_status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.extra_fields = extra_fields


def _current_request_id(request: Request) -> str:
    req_id = getattr(request.state, "request_id", "") or request_id_var.get()
    if not req_id:
        req_id = new_uuid7_str()
    return str(req_id)


def build_problem_response(
    *,
    status: int,
    code: ErrorCode,
    title: str,
    detail: str,
    request_id: str,
    headers: dict[str, str] | None = None,
    extra_fields: dict[str, object] | None = None,
) -> JSONResponse:
    """Build a standard application/problem+json response."""
    problem = ProblemDetail(
        type="about:blank",
        title=title,
        status=status,
        detail=detail,
        code=code,
        request_id=request_id,
    )
    payload: dict[str, object] = problem.model_dump(mode="json")
    if extra_fields:
        payload.update(extra_fields)
    return JSONResponse(
        status_code=status,
        content=payload,
        media_type=PROBLEM_JSON_MEDIA_TYPE,
        headers=headers,
    )


def problem_response(exc: AppError, *, request_id: str) -> JSONResponse:
    """Build an application/problem+json response directly from an AppError instance."""
    return build_problem_response(
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        request_id=request_id,
        headers=exc.headers,
        extra_fields=exc.extra_fields,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register application/problem+json handlers for AppError, 422 validation, and 500 errors."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        req_id = _current_request_id(request)
        if exc.code == ErrorCode.AUTH_INVALID_TOKEN:
            logger.warning(
                "Authentication token rejected",
                extra={
                    "request_id": req_id,
                    "status_code": exc.status,
                    "error_code": exc.code.value,
                },
            )
        return build_problem_response(
            status=exc.status,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            request_id=req_id,
            headers=exc.headers,
            extra_fields=exc.extra_fields,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """Return 422 with field paths only; never echo values that may hold PII (Rules.md §3)."""
        req_id = _current_request_id(request)
        field_paths: list[str] = []
        for err in exc.errors():
            loc = err.get("loc", ())
            path = ".".join(str(part) for part in loc)
            if path:
                field_paths.append(path)
        unique_paths = sorted(set(field_paths))
        detail = (
            f"Validation failed for fields: {', '.join(unique_paths)}"
            if unique_paths
            else "Request validation failed."
        )
        return build_problem_response(
            status=422,
            code=ErrorCode.VALIDATION,
            title="Validation Error",
            detail=detail,
            request_id=req_id,
            extra_fields={"fields": unique_paths},
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        """Return 500 with request_id only; log masked stack trace internally (Rules.md §3)."""
        req_id = _current_request_id(request)
        logger.exception(
            "Unhandled server exception",
            exc_info=exc,
            extra={
                "request_id": req_id,
                "status_code": 500,
                "error_code": ErrorCode.INTERNAL.value,
            },
        )
        return build_problem_response(
            status=500,
            code=ErrorCode.INTERNAL,
            title="Internal Server Error",
            detail="An unexpected internal error occurred.",
            request_id=req_id,
        )


register_error_handlers = register_exception_handlers

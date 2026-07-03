from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum, unique
from typing import TypedDict

type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
type ErrorDetails = dict[str, JsonValue]
type ErrorDetailsInput = Mapping[str, JsonValue]


class ErrorPayload(TypedDict):
    code: str
    message: str
    details: ErrorDetails


class ErrorResponse(TypedDict):
    error: ErrorPayload


@unique
class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    SEMANTIC_VALIDATION_ERROR = "SEMANTIC_VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"


def build_error_response(
    code: ErrorCode,
    message: str,
    details: ErrorDetailsInput | None = None,
) -> ErrorResponse:
    response_details: ErrorDetails = dict(details) if details is not None else {}
    return {
        "error": {
            "code": code.value,
            "message": message,
            "details": response_details,
        },
    }

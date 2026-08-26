from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

from easyauth.accounts.directory_references import (
    AmbiguousDirectoryReferenceError,
    InvalidDirectoryReferenceError,
)
from easyauth.accounts.directory_snapshot import build_directory_snapshot
from easyauth.api.errors import ErrorCode, build_error_response
from easyauth.api.responses import json_response
from easyauth.audit.directory_audit import (
    DIRECTORY_AUDIT_ACTION,
    DIRECTORY_AUDIT_TARGET_TYPE,
    record_directory_audit_bucket,
)
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from django.http import JsonResponse

    from easyauth.api.errors import JsonValue
    from easyauth.applications.services import AppPrincipal

_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_TOO_MANY_REQUESTS_MESSAGE: Final = "请求过于频繁, 请稍后再试。"
_SNAPSHOT_CONFLICT_MESSAGE: Final = "目录快照已变化, 请从第一页重新读取。"
_RETRY_AFTER_HEADER: Final = "Retry-After"
_CACHE_CONTROL_HEADER: Final = "Cache-Control"
_CACHE_CONTROL_VALUE: Final = "private, max-age=60"


def record_directory_audit(
    *,
    principal: AppPrincipal,
    endpoint: str,
    result_count: int,
    q_present: bool,
    aggregated: bool,
) -> None:
    if aggregated:
        _record_aggregated_list_audit(
            principal=principal,
            endpoint=endpoint,
            result_count=result_count,
            q_present=q_present,
        )
        return
    _ = AuditService.record(
        AuditRecord(
            actor_type="app",
            actor_id=principal.app_key,
            action=DIRECTORY_AUDIT_ACTION,
            target_type=DIRECTORY_AUDIT_TARGET_TYPE,
            target_id=principal.app_key,
            metadata={
                "endpoint": endpoint,
                "q_present": q_present,
                "result_count": result_count,
                "credential_id": principal.credential_id,
            },
        ),
    )


def _record_aggregated_list_audit(
    *,
    principal: AppPrincipal,
    endpoint: str,
    result_count: int,
    q_present: bool,
) -> None:
    record_directory_audit_bucket(
        app_key=principal.app_key,
        endpoint=endpoint,
        result_count=result_count,
        q_present=q_present,
        credential_id=principal.credential_id,
    )


def directory_response(
    payload: dict[str, JsonValue],
    *,
    directory_snapshot: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    payload["directory_snapshot"] = directory_snapshot or build_directory_snapshot()
    response = json_response(payload, status=HTTPStatus.OK)
    response[_CACHE_CONTROL_HEADER] = _CACHE_CONTROL_VALUE
    return response


def authentication_failed_response() -> JsonResponse:
    return json_response(
        build_error_response(ErrorCode.AUTHENTICATION_FAILED, _AUTHENTICATION_FAILED_MESSAGE),
        status=HTTPStatus.UNAUTHORIZED,
    )


def permission_denied_response(message: str) -> JsonResponse:
    return json_response(
        build_error_response(ErrorCode.PERMISSION_DENIED, message),
        status=HTTPStatus.FORBIDDEN,
    )


def not_found_response(message: str, *, reason: str) -> JsonResponse:
    return json_response(
        build_error_response(
            ErrorCode.NOT_FOUND,
            message,
            {"reason": reason},
        ),
        status=HTTPStatus.NOT_FOUND,
    )


def snapshot_conflict_response(
    *,
    reason: str,
    expected_snapshot_id: str,
    actual_snapshot_id: str,
) -> JsonResponse:
    return json_response(
        build_error_response(
            ErrorCode.CONFLICT,
            _SNAPSHOT_CONFLICT_MESSAGE,
            {
                "reason": reason,
                "expected_snapshot_id": expected_snapshot_id,
                "actual_snapshot_id": actual_snapshot_id,
            },
        ),
        status=HTTPStatus.CONFLICT,
    )


def reference_error_response(
    error: AmbiguousDirectoryReferenceError | InvalidDirectoryReferenceError,
) -> JsonResponse:
    if isinstance(error, AmbiguousDirectoryReferenceError):
        return json_response(
            build_error_response(
                ErrorCode.CONFLICT,
                "目录引用在多个企业作用域中存在, 请使用 scoped ref。",
                {
                    "reason": f"ambiguous_{error.reference_type}_ref",
                    "reference": error.reference,
                    "candidate_refs": list(error.candidate_refs),
                },
            ),
            status=HTTPStatus.CONFLICT,
        )
    return json_response(
        build_error_response(
            ErrorCode.VALIDATION_ERROR,
            str(error),
            {"reason": "invalid_directory_ref"},
        ),
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


def too_many_requests_response(retry_after_seconds: int) -> JsonResponse:
    response = json_response(
        build_error_response(ErrorCode.THROTTLED, _TOO_MANY_REQUESTS_MESSAGE),
        status=HTTPStatus.TOO_MANY_REQUESTS,
    )
    response[_RETRY_AFTER_HEADER] = str(retry_after_seconds)
    return response

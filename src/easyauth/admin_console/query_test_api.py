from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.query_tester import (
    PermissionQueryTestResult,
    run_permission_query_test,
)
from easyauth.admin_console.request_guards import require_console_actor, require_post
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.permission_query_payloads import expanded_grant_payload
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_view_app

type AppLookupResult = App | JsonResponse


class _PermissionQueryTestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=128)
    token: str = Field(min_length=1)


def console_permission_query_test(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    match _app_for_actor(actor, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    if response := require_post(request):
        return response
    try:
        payload = _PermissionQueryTestPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    result = run_permission_query_test(
        app=app,
        user_id=payload.user_id,
        plaintext_token=payload.token,
        actor_id=actor.user_id,
    )
    return _result_response(app=app, user_id=payload.user_id.strip(), result=result)


def _app_for_actor(actor: ConsoleActor, app_key: str) -> AppLookupResult:
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    if not can_view_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "无权限访问该应用。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app


def _result_response(
    *,
    app: App,
    user_id: str,
    result: PermissionQueryTestResult,
) -> JsonResponse:
    if result.status_code == HTTPStatus.OK:
        return _json_response(_success_payload(app=app, user_id=user_id, result=result))
    return _error_response(
        _error_code(result),
        result.explanation,
        {
            "app_key": app.app_key,
            "user_id": user_id,
            "status_code": result.status_code,
            "code": result.code,
        },
        status=result.status_code,
    )


def _success_payload(
    *,
    app: App,
    user_id: str,
    result: PermissionQueryTestResult,
) -> dict[str, JsonValue]:
    groups: list[JsonValue] = [
        {"key": group.key, "kind": group.kind, "name": group.name}
        for group in result.groups
    ]
    grants: list[JsonValue] = [expanded_grant_payload(grant) for grant in result.grants]
    return {
        "app_key": app.app_key,
        "user_id": user_id,
        "allowed": len(result.groups) > 0 or len(result.grants) > 0,
        "groups": groups,
        "grants": grants,
        "grant_version": result.grant_version,
        "catalog_version": result.catalog_version,
        "snapshot_version": result.snapshot_version,
        "expires_at": None if result.expires_at is None else result.expires_at.isoformat(),
        "status_code": result.status_code,
        "code": result.code,
        "explanation": result.explanation,
    }


def _error_code(result: PermissionQueryTestResult) -> ErrorCode:
    match result.code:
        case "validation_error":
            return ErrorCode.VALIDATION_ERROR
        case "authentication_failed":
            return ErrorCode.AUTHENTICATION_FAILED
        case "permission_denied":
            return ErrorCode.PERMISSION_DENIED
        case "internal_permission_query_error":
            return ErrorCode.INTERNAL_ERROR
        case _:
            return ErrorCode.INTERNAL_ERROR

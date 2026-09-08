from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import ConfigDict, Field, ValidationError

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.grant_row_payloads import (
    access_grant_row_queryset,
    serialize_access_grant_row,
)
from easyauth.admin_console.grant_write_common import (
    AdminGrantLookupError,
    AdminGrantSemanticError,
    AdminGrantWritePayload,
    resolve_admin_grant_targets,
)
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App
from easyauth.grants.direct_grant import apply_admin_direct_grant
from easyauth.grants.managed_users import ManagedUsersResolutionUnavailableError
from easyauth.grants.models import GRANT_STATUS_ACTIVE, AccessGrant
from easyauth.grants.services import GrantMutationExpiredError

USER_NOT_FOUND_MESSAGE = "用户不存在。"
USER_INACTIVE_MESSAGE = "用户当前不是在职状态,无法授予权限。"
GRANT_EXPIRED_MESSAGE = "授权到期时间必须晚于当前时间。"
APP_NOT_FOUND_MESSAGE = "应用不存在。"


class DirectGrantRequestPayload(AdminGrantWritePayload):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    user_id: str = Field(min_length=1, max_length=128)


def console_direct_grants(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case str() as actor_id:
            pass
    if request.method != "POST":
        return method_not_allowed_response()
    return _create_direct_grant(request, actor_id=actor_id)


def _create_direct_grant(request: HttpRequest, *, actor_id: str) -> JsonResponse:
    try:
        payload = DirectGrantRequestPayload.model_validate_json(request.body)
        user = _active_user_for_id(payload.user_id)
        targets = resolve_admin_grant_targets(payload)
        with transaction.atomic():
            grant = apply_admin_direct_grant(user=user, targets=targets, actor_id=actor_id)
            row = serialize_access_grant_row(_grant_for_row(grant))
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except AdminGrantLookupError as exc:
        return error_response(exc.code, exc.message, exc.details, status=exc.status)
    except AdminGrantSemanticError as exc:
        return _semantic_error_response(exc)
    except GrantMutationExpiredError:
        return _semantic_error_response(
            AdminGrantSemanticError(GRANT_EXPIRED_MESSAGE, (GRANT_EXPIRED_MESSAGE,)),
        )
    except ManagedUsersResolutionUnavailableError as exc:
        return error_response(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            str(exc),
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    return json_response(
        {"data": {"grant": row}},
        status=HTTPStatus.CREATED,
    )


def _active_user_for_id(user_id: str) -> UserMirror:
    user = UserMirror.objects.filter(authentik_user_id=user_id).first()
    if user is None:
        raise AdminGrantLookupError(
            USER_NOT_FOUND_MESSAGE,
            {"user_id": user_id},
            HTTPStatus.NOT_FOUND,
            ErrorCode.NOT_FOUND,
        )
    if user.status != USER_STATUS_ACTIVE:
        raise AdminGrantLookupError(
            USER_INACTIVE_MESSAGE,
            {"user_id": user_id},
            HTTPStatus.CONFLICT,
            ErrorCode.CONFLICT,
        )
    return user


def _semantic_error_response(exc: AdminGrantSemanticError) -> JsonResponse:
    errors: list[JsonValue] = []
    errors.extend(exc.errors)
    return error_response(
        exc.code,
        exc.message,
        {"errors": errors},
        status=exc.status,
    )


def _grant_for_row(grant: AccessGrant) -> AccessGrant:
    return access_grant_row_queryset().get(pk=grant.id)


def console_user_app_current_grant(
    request: HttpRequest,
    user_id: str,
    app_key: str,
) -> JsonResponse:
    match require_superuser(request):
        case JsonResponse() as response:
            return response
        case str():
            pass
    if request.method != "GET":
        return method_not_allowed_response()
    user = UserMirror.objects.filter(authentik_user_id=user_id).first()
    if user is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            USER_NOT_FOUND_MESSAGE,
            {"user_id": user_id},
            status=HTTPStatus.NOT_FOUND,
        )
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            APP_NOT_FOUND_MESSAGE,
            {"app_key": app_key},
            status=HTTPStatus.NOT_FOUND,
        )
    grant = (
        access_grant_row_queryset()
        .filter(user=user, app=app, is_current=True, status=GRANT_STATUS_ACTIVE)
        .first()
    )
    try:
        serialized = None if grant is None else serialize_access_grant_row(grant)
    except ManagedUsersResolutionUnavailableError as exc:
        return error_response(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            str(exc),
            status=HTTPStatus.SERVICE_UNAVAILABLE,
        )
    return json_response(
        {"grant": serialized},
    )

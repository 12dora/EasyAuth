from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, cast

from django.http import HttpRequest, JsonResponse
from pydantic import ConfigDict, Field, ValidationError

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.grant_write_common import (
    AdminGrantLookupError,
    AdminGrantSemanticError,
    AdminGrantWritePayload,
    resolve_admin_grant_targets,
)
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.grants.direct_grant import apply_admin_direct_grant
from easyauth.grants.models import MEMBERSHIP_SOURCE_USER, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.services import GrantMutationExpiredError

if TYPE_CHECKING:
    from easyauth.admin_console.grant_write_common import ResolvedAdminGrantTargets
    from easyauth.grants.models import AccessGrant

USER_NOT_FOUND_MESSAGE = "用户不存在。"
USER_INACTIVE_MESSAGE = "用户当前不是在职状态,无法授予权限。"
GRANT_EXPIRED_MESSAGE = "授权到期时间必须晚于当前时间。"


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
        grant = apply_admin_direct_grant(user=user, targets=targets, actor_id=actor_id)
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
    return json_response(
        {"data": _direct_grant_response(grant, targets)},
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


def _direct_grant_response(
    grant: AccessGrant,
    targets: ResolvedAdminGrantTargets,
) -> dict[str, JsonValue]:
    group_keys = list(
        AccessGrantGroup.objects.filter(grant=grant, source=MEMBERSHIP_SOURCE_USER)
        .order_by("authorization_group__key")
        .values_list("authorization_group__key", flat=True),
    )
    direct_rows = (
        AccessGrantPermission.objects.filter(grant=grant, source=MEMBERSHIP_SOURCE_USER)
        .select_related("permission")
        .order_by("permission__key", "scope_key")
    )
    direct_grants: list[JsonValue] = [
        {"permission": row.permission.key, "scope": row.scope_key} for row in direct_rows
    ]
    return {
        "grant_id": grant.id,
        "version": grant.version,
        "user_id": grant.user.authentik_user_id,
        "app_key": grant.app.app_key,
        "authorization_group_keys": cast("list[JsonValue]", list(group_keys)),
        "direct_grants": direct_grants,
        "grant_type": targets.grant_type,
        "grant_expires_at": datetime_value(targets.grant_expires_at),
    }

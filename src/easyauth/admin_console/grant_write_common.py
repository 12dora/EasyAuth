from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Literal, override

from django.utils import timezone
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import AppScope
from easyauth.portal.access_request_payloads import (
    APP_NOT_REQUESTABLE_MESSAGE,
    PERMISSION_NOT_REQUESTABLE_MESSAGE,
    ROLE_NOT_REQUESTABLE_MESSAGE,
    AccessRequestTargetError,
    DirectGrantPayload,
    RoleKey,
    app_for_key,
    authorization_groups_for_keys,
    direct_grants_for_payloads,
)

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
    from easyauth.applications.models import App, AuthorizationGroup, Permission

type AdminGrantType = Literal["permanent", "timed"]

EMPTY_TARGETS_MESSAGE = "至少选择一个授权组或权限。"
PERMANENT_EXPIRY_MESSAGE = "永久授权不得填写到期时间。"
TIMED_EXPIRY_REQUIRED_MESSAGE = "限时授权必须填写到期时间。"
TIMED_EXPIRY_FUTURE_MESSAGE = "限时授权的到期时间必须晚于当前时间。"
DUPLICATE_GROUPS_MESSAGE = "授权组不能重复。"
DUPLICATE_DIRECTS_MESSAGE = "直接权限不能重复。"
APP_NOT_FOUND_MESSAGE = "应用不存在。"
GROUP_NOT_FOUND_MESSAGE = "授权组不存在。"
PERMISSION_NOT_FOUND_MESSAGE = "权限不存在。"


@dataclass(frozen=True, slots=True)
class AdminGrantSemanticError(Exception):
    message: str
    errors: tuple[str, ...]
    status: HTTPStatus = HTTPStatus.UNPROCESSABLE_ENTITY
    code: ErrorCode = ErrorCode.SEMANTIC_VALIDATION_ERROR

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class AdminGrantLookupError(Exception):
    message: str
    details: dict[str, JsonValue]
    status: HTTPStatus
    code: ErrorCode

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ResolvedAdminGrantTargets:
    app: App
    authorization_groups: tuple[AuthorizationGroup, ...]
    direct_grants: tuple[ScopedAccessRequestGrant, ...]
    grant_type: AdminGrantType
    grant_expires_at: datetime | None
    reason: str


class AdminGrantWritePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=128)
    authorization_group_keys: tuple[RoleKey, ...] = Field(default=(), max_length=20)
    direct_grants: tuple[DirectGrantPayload, ...] = ()
    grant_type: AdminGrantType
    grant_expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=1000)


def resolve_admin_grant_targets(payload: AdminGrantWritePayload) -> ResolvedAdminGrantTargets:
    app = _app_for_admin_key(payload.app_key)
    errors = _expiration_errors(payload.grant_type, payload.grant_expires_at)
    if not payload.authorization_group_keys and not payload.direct_grants:
        errors.append(EMPTY_TARGETS_MESSAGE)
    errors.extend(_duplicate_target_errors(payload))
    groups = _authorization_groups(app, payload.authorization_group_keys)
    direct_grants = _direct_grants(app, payload.direct_grants)
    errors.extend(_admin_group_errors(app, groups))
    errors.extend(_admin_direct_grant_errors(app, direct_grants))
    if errors:
        raise AdminGrantSemanticError(errors[0], tuple(errors))
    return ResolvedAdminGrantTargets(
        app=app,
        authorization_groups=groups,
        direct_grants=direct_grants,
        grant_type=payload.grant_type,
        grant_expires_at=payload.grant_expires_at,
        reason=payload.reason,
    )


def _app_for_admin_key(app_key: str) -> App:
    try:
        return app_for_key(app_key)
    except AccessRequestTargetError as exc:
        if exc.message == APP_NOT_REQUESTABLE_MESSAGE:
            raise AdminGrantLookupError(
                APP_NOT_FOUND_MESSAGE,
                {"app_key": app_key},
                HTTPStatus.NOT_FOUND,
                ErrorCode.NOT_FOUND,
            ) from exc
        raise AdminGrantSemanticError(exc.message, (exc.message,)) from exc


def _authorization_groups(
    app: App,
    authorization_group_keys: tuple[str, ...],
) -> tuple[AuthorizationGroup, ...]:
    try:
        return authorization_groups_for_keys(
            app=app,
            authorization_group_keys=authorization_group_keys,
        )
    except AccessRequestTargetError as exc:
        if exc.message == ROLE_NOT_REQUESTABLE_MESSAGE:
            raise AdminGrantSemanticError(
                GROUP_NOT_FOUND_MESSAGE, (GROUP_NOT_FOUND_MESSAGE,)
            ) from exc
        raise AdminGrantSemanticError(exc.message, (exc.message,)) from exc


def _direct_grants(
    app: App,
    payloads: tuple[DirectGrantPayload, ...],
) -> tuple[ScopedAccessRequestGrant, ...]:
    try:
        return direct_grants_for_payloads(app=app, direct_grants=payloads)
    except AccessRequestTargetError as exc:
        if exc.message == PERMISSION_NOT_REQUESTABLE_MESSAGE:
            raise AdminGrantSemanticError(
                PERMISSION_NOT_FOUND_MESSAGE,
                (PERMISSION_NOT_FOUND_MESSAGE,),
            ) from exc
        raise AdminGrantSemanticError(exc.message, (exc.message,)) from exc


def _expiration_errors(
    grant_type: AdminGrantType,
    grant_expires_at: datetime | None,
) -> list[str]:
    if grant_type == "permanent":
        return [] if grant_expires_at is None else [PERMANENT_EXPIRY_MESSAGE]
    if grant_expires_at is None:
        return [TIMED_EXPIRY_REQUIRED_MESSAGE]
    if grant_expires_at <= timezone.now():
        return [TIMED_EXPIRY_FUTURE_MESSAGE]
    return []


def _duplicate_target_errors(payload: AdminGrantWritePayload) -> list[str]:
    errors: list[str] = []
    if len(payload.authorization_group_keys) != len(set(payload.authorization_group_keys)):
        errors.append(DUPLICATE_GROUPS_MESSAGE)
    identities = tuple((item.permission, item.scope) for item in payload.direct_grants)
    if len(identities) != len(set(identities)):
        errors.append(DUPLICATE_DIRECTS_MESSAGE)
    return errors


def _admin_group_errors(app: App, groups: tuple[AuthorizationGroup, ...]) -> tuple[str, ...]:
    errors: list[str] = []
    for group in groups:
        if group.app_id != app.id:
            errors.append(f"{group.key}: 授权组不属于该应用。")
        elif not group.is_active:
            errors.append(f"{group.key}: 授权组未启用。")
    return tuple(errors)


def _admin_direct_grant_errors(
    app: App,
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> tuple[str, ...]:
    active_scope_keys = frozenset(
        AppScope.objects.filter(
            app_id=app.id,
            key__in=tuple({grant.scope_key for grant in direct_grants}),
            is_active=True,
        ).values_list("key", flat=True),
    )
    errors: list[str] = []
    for grant in direct_grants:
        errors.extend(
            f"{grant.permission.key}:{grant.scope_key}: {message}"
            for message in _direct_grant_error_messages(
                app,
                grant.permission,
                grant.scope_key,
                active_scope_keys=active_scope_keys,
            )
        )
    return tuple(errors)


def _direct_grant_error_messages(
    app: App,
    permission: Permission,
    scope_key: str,
    *,
    active_scope_keys: frozenset[str],
) -> tuple[str, ...]:
    errors: list[str] = []
    raw_supported_scopes = permission.supported_scopes
    supported_scope_values = raw_supported_scopes if isinstance(raw_supported_scopes, list) else []
    supported_scopes = {item for item in supported_scope_values if isinstance(item, str)}
    if permission.app_id != app.id:
        errors.append("权限不属于该应用。")
    if not permission.is_active:
        errors.append("权限未启用。")
    if permission.deprecated_at is not None:
        errors.append("权限已废弃。")
    if scope_key not in supported_scopes:
        errors.append("该权限不支持指定的授权范围。")
    if scope_key not in active_scope_keys:
        errors.append("授权范围不属于该应用或未启用。")
    return tuple(errors)

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, override

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from easyauth.applications.models import App, AuthorizationGroup, Permission

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

type RoleKey = Annotated[str, Field(min_length=1, max_length=128)]
type PermissionKey = Annotated[str, Field(min_length=1, max_length=128)]
type ScopeKey = Annotated[str, Field(min_length=1, max_length=64)]
type GrantType = Literal["permanent", "timed"]
type RequestType = Literal["grant", "change", "revoke", "renew"]

APP_NOT_REQUESTABLE_MESSAGE = "应用当前不可申请。"
ROLE_NOT_REQUESTABLE_MESSAGE = "角色当前不可申请。"
PERMISSION_NOT_REQUESTABLE_MESSAGE = "权限当前不可申请。"


class DirectGrantPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    permission: PermissionKey
    scope: ScopeKey


class AccessRequestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=128)
    request_type: RequestType = "grant"
    authorization_group_keys: tuple[RoleKey, ...] = Field(default=(), max_length=20)
    direct_grants: tuple[DirectGrantPayload, ...] = Field(default=(), max_length=50)
    grant_type: GrantType
    grant_expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=1000)


@dataclass(frozen=True, slots=True)
class AccessRequestTargetError(Exception):
    message: str
    details: dict[str, JsonValue]

    @override
    def __str__(self) -> str:
        return self.message


def app_for_key(app_key: str) -> App:
    app = App.objects.filter(app_key=app_key, is_active=True).first()
    if app is None:
        raise AccessRequestTargetError(APP_NOT_REQUESTABLE_MESSAGE, {"app_key": app_key})
    return app


@dataclass(frozen=True, slots=True)
class DirectGrantTarget:
    permission: Permission
    scope_key: str


def authorization_groups_for_keys(
    *,
    app: App,
    authorization_group_keys: tuple[str, ...],
) -> tuple[AuthorizationGroup, ...]:
    group_by_key = {
        group.key: group
        for group in AuthorizationGroup.objects.filter(app=app, key__in=authorization_group_keys)
    }
    missing_group_keys = tuple(key for key in authorization_group_keys if key not in group_by_key)
    if missing_group_keys:
        raise AccessRequestTargetError(
            ROLE_NOT_REQUESTABLE_MESSAGE,
            {"authorization_group_keys": _json_strings(missing_group_keys)},
        )
    return tuple(group_by_key[key] for key in authorization_group_keys)


def direct_grants_for_payloads(
    *,
    app: App,
    direct_grants: tuple[DirectGrantPayload, ...],
) -> tuple[DirectGrantTarget, ...]:
    permission_keys = tuple(grant.permission for grant in direct_grants)
    permission_by_key = {
        permission.key: permission
        for permission in Permission.objects.filter(app=app, key__in=permission_keys)
    }
    missing_permission_keys = tuple(key for key in permission_keys if key not in permission_by_key)
    if missing_permission_keys:
        raise AccessRequestTargetError(
            PERMISSION_NOT_REQUESTABLE_MESSAGE,
            {"permission_keys": _json_strings(missing_permission_keys)},
        )
    return tuple(
        DirectGrantTarget(
            permission=permission_by_key[direct_grant.permission],
            scope_key=direct_grant.scope,
        )
        for direct_grant in direct_grants
    )


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result

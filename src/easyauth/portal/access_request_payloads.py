from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, ClassVar, Literal, override

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
from easyauth.applications.models import App, AuthorizationGroup, Permission

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

type RoleKey = Annotated[str, Field(min_length=1, max_length=128)]
type PermissionKey = Annotated[str, Field(min_length=1, max_length=128)]
type ScopeKey = Annotated[str, Field(min_length=1, max_length=64)]
type ApproverUserId = Annotated[str, Field(min_length=1, max_length=128)]
type GrantType = Literal["permanent", "timed"]
type RequestType = Literal["grant", "change", "revoke", "renew"]

APP_NOT_REQUESTABLE_MESSAGE = "应用当前不可申请。"
ROLE_NOT_REQUESTABLE_MESSAGE = "角色当前不可申请。"
PERMISSION_NOT_REQUESTABLE_MESSAGE = "权限当前不可申请。"
GRANT_BASE_FORBIDDEN_MESSAGE = "grant 申请不能包含 base_grant_id 或 base_grant_revision"
LIFECYCLE_BASE_REQUIRED_MESSAGE = (
    "change/revoke/renew 申请必须包含 base_grant_id 和 base_grant_revision"
)


class DirectGrantPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    permission: PermissionKey
    scope: ScopeKey


class AccessRequestPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=128)
    request_type: RequestType = "grant"
    base_grant_id: int | None = Field(default=None, ge=1)
    base_grant_revision: int | None = Field(default=None, ge=1)
    authorization_group_keys: tuple[RoleKey, ...] = Field(default=(), max_length=20)
    direct_grants: tuple[DirectGrantPayload, ...] = ()
    approver_user_ids: tuple[ApproverUserId, ...] = Field(min_length=1, max_length=20)
    grant_type: GrantType
    grant_expires_at: AwareDatetime | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_base_grant_shape(self) -> AccessRequestPayload:
        has_base = self.base_grant_id is not None and self.base_grant_revision is not None
        if self.request_type == "grant":
            if self.base_grant_id is not None or self.base_grant_revision is not None:
                message = GRANT_BASE_FORBIDDEN_MESSAGE
                raise ValueError(message)
            return self
        if not has_base:
            message = LIFECYCLE_BASE_REQUIRED_MESSAGE
            raise ValueError(message)
        return self


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
) -> tuple[ScopedAccessRequestGrant, ...]:
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
        ScopedAccessRequestGrant(
            permission=permission_by_key[direct_grant.permission],
            scope_key=direct_grant.scope,
        )
        for direct_grant in direct_grants
    )


def _json_strings(values: tuple[str, ...]) -> list[JsonValue]:
    result: list[JsonValue] = []
    result.extend(values)
    return result

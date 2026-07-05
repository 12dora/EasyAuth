from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, cast

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.accounts.models import UserMirror
from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.request_guards import require_console_actor, require_post
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.managed_scope_policy import ManagedScopePolicyService
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    App,
    ManagedScopePolicy,
)
from easyauth.applications.ownership import can_manage_app
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
)

if TYPE_CHECKING:
    from easyauth.applications.ownership import ConsoleActor
    from easyauth.integrations.authentik.directory_payloads import DingTalkManagedUsers

type AppLookupResult = App | JsonResponse
type PayloadLookupResult = _ManagedUsersPreviewPayload | JsonResponse
type PolicyLookupResult = ManagedScopePolicy | JsonResponse
type UserLookupResult = UserMirror | JsonResponse
type ManagedUsersLookupResult = DingTalkManagedUsers | JsonResponse


class _ManagedUsersPreviewPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    user_id: str = Field(min_length=1, max_length=128)


def console_managed_users_preview(request: HttpRequest, app_key: str) -> JsonResponse:
    actor = require_console_actor(request)
    if isinstance(actor, JsonResponse):
        return actor

    app = _app_for_actor(actor, app_key)
    if isinstance(app, JsonResponse):
        return app

    if response := require_post(request):
        return response

    payload = _payload_from_request(request)
    if isinstance(payload, JsonResponse):
        return payload

    return _preview_response(actor=actor, app=app, user_id=payload.user_id)


def _payload_from_request(request: HttpRequest) -> PayloadLookupResult:
    try:
        return _ManagedUsersPreviewPayload.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )


def _preview_response(*, actor: ConsoleActor, app: App, user_id: str) -> JsonResponse:
    policy = _app_default_policy(app)
    if isinstance(policy, JsonResponse):
        return policy

    if policy.resolver != MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN:
        return _bad_request(
            "管理范围解析器暂不支持。",
            "managed_scope_resolver_unsupported",
        )

    user = _target_user(user_id)
    if isinstance(user, JsonResponse):
        return user

    managed_users = _managed_users_for_user(user)
    if isinstance(managed_users, JsonResponse):
        return managed_users
    # 每次成功预览都记审计(actor + target), 使"谁向谁汇报"的探测可追溯。
    _record_preview(actor=actor, app=app, user_id=user_id)
    return json_response(_success_payload(user=user, managed_users=managed_users))


def _record_preview(*, actor: ConsoleActor, app: App, user_id: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor.user_id,
            action="managed_users_preview",
            target_type="user_permission",
            target_id=user_id,
            metadata={"app_key": app.app_key},
        ),
    )


def _managed_users_for_user(user: UserMirror) -> ManagedUsersLookupResult:
    if not user.dingtalk_corp_id or not user.dingtalk_userid:
        return _bad_request(
            "用户缺少钉钉组织绑定。",
            "managed_scope_user_dingtalk_binding_missing",
        )

    try:
        managed_users = AuthentikDirectoryClient.from_settings().get_managed_users(
            user.dingtalk_corp_id,
            user.dingtalk_userid,
        )
    except AuthentikDirectoryError:
        return _bad_request(
            "钉钉目录暂不可用。",
            "managed_scope_directory_unavailable",
        )
    if managed_users.stale:
        return _bad_request(
            "钉钉目录数据已过期。",
            "managed_scope_directory_stale",
        )
    return managed_users


def _app_for_actor(actor: ConsoleActor, app_key: str) -> AppLookupResult:
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    # 预览会返回目标用户的钉钉主管链下属集合, 属组织架构 oracle: 收紧为 owner/superuser。
    if not can_manage_app(actor, app):
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            "无权限访问该应用。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app


def _app_default_policy(app: App) -> PolicyLookupResult:
    policy = ManagedScopePolicyService.get_app_default_policy(app=app)
    if (
        policy is None
        or not policy.enabled
        or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED
    ):
        return _bad_request(
            "应用未配置有效的 MANAGED_USERS 默认策略。",
            "managed_scope_policy_missing",
        )
    return policy


def _target_user(user_id: str) -> UserLookupResult:
    user = UserMirror.objects.filter(authentik_user_id=user_id).first()
    if user is None:
        return _bad_request(
            "用户不存在。",
            "managed_scope_user_not_found",
        )
    return user


def _success_payload(
    *,
    user: UserMirror,
    managed_users: DingTalkManagedUsers,
) -> dict[str, JsonValue]:
    user_ids = [
        user_id
        for user_id in managed_users.active_authentik_user_ids
        if user_id != user.authentik_user_id
    ]
    resolved: dict[str, JsonValue] = {
        "user_ids": cast("list[JsonValue]", user_ids),
        "resolver": MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
        "resolved_at": managed_users.resolved_at,
    }
    return {
        "resolved": {
            "user_ids": resolved["user_ids"],
            "resolver": resolved["resolver"],
            "resolved_at": resolved["resolved_at"],
        },
        "diagnostics": [],
    }


def _bad_request(message: str, error_code: str) -> JsonResponse:
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        {"diagnostics": [{"error_code": error_code}]},
        status=HTTPStatus.BAD_REQUEST,
    )

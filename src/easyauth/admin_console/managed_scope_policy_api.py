from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Final

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.api_responses import method_not_allowed_response
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.managed_scope_policy import (
    EffectiveManagedScopePolicy,
    ManagedScopePolicyService,
)
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    MANAGED_SCOPE_POLICY_RESOLVERS,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
    App,
    ManagedScopePolicy,
)
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app
from easyauth.audit.services import AuditRecord, AuditService

type AppApiResult = App | JsonResponse
type AppWriteContextResult = tuple[App, ConsoleActor] | JsonResponse
type ManagedScopePolicyPayload = dict[str, JsonValue]

INVALID_RESOLVER_MESSAGE: Final = "resolver 必须为 dingtalk_manager_chain 或 disabled。"


class ManagedScopePolicyValuePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    mode: str = Field(default="override", max_length=64)
    enabled: bool
    resolver: str = Field(max_length=64)

    @field_validator("resolver")
    @classmethod
    def validate_resolver(cls, value: str) -> str:
        if value not in MANAGED_SCOPE_POLICY_RESOLVERS:
            raise ValueError(INVALID_RESOLVER_MESSAGE)
        return value


class ManagedScopePolicyPatchPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    managed_scope_policy: ManagedScopePolicyValuePayload | None


def console_managed_scope_policy(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "GET":
        match _read_context(request, app_key):
            case App() as app:
                return _json_response(_policy_payload(app))
            case JsonResponse() as response:
                return response
    if request.method == "PATCH":
        match _write_context(request, app_key):
            case (App() as app, ConsoleActor() as actor):
                return _patch_policy(request, app, actor)
            case JsonResponse() as response:
                return response
    return method_not_allowed_response()


def _patch_policy(request: HttpRequest, app: App, actor: ConsoleActor) -> JsonResponse:
    try:
        payload = ManagedScopePolicyPatchPayload.model_validate_json(request.body)
    except ValidationError as error:
        return _validation_error_response("管理范围策略参数无效。", {"errors": str(error)})
    try:
        normalized = (
            _normalized_policy_payload(payload.managed_scope_policy)
            if payload.managed_scope_policy is not None
            else None
        )
    except ValueError as error:
        return _validation_error_response(str(error))

    with transaction.atomic():
        if normalized is None:
            _ = ManagedScopePolicy.objects.filter(
                app=app,
                target_type=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
                target_id=app.id,
                scope=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
            ).delete()
            _record_managed_scope_policy_updated(app=app, actor=actor, resolver="deleted")
        else:
            _policy, _created = ManagedScopePolicy.objects.update_or_create(
                app=app,
                target_type=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
                target_id=app.id,
                scope=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
                defaults={
                    "resolver": normalized.resolver,
                    "enabled": normalized.enabled,
                },
            )
            _record_managed_scope_policy_updated(app=app, actor=actor, resolver=normalized.resolver)

    return _json_response(_policy_payload(app))


def _normalized_policy_payload(
    payload: ManagedScopePolicyValuePayload,
) -> ManagedScopePolicyValuePayload:
    if (
        MANAGED_SCOPE_POLICY_RESOLVER_DISABLED in {payload.mode, payload.resolver}
        or not payload.enabled
    ):
        return ManagedScopePolicyValuePayload(
            mode=MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
            resolver=MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
            enabled=True,
        )
    if payload.mode not in {"override", MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN}:
        message = "mode 必须为 override 或 disabled。"
        raise ValueError(message)
    return ManagedScopePolicyValuePayload(
        mode="override",
        resolver=MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN,
        enabled=True,
    )


def _read_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(ErrorCode.NOT_FOUND, "App 不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_view_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner/developer 可以访问该 App 管理范围策略。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app


def _write_context(request: HttpRequest, app_key: str) -> AppWriteContextResult:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _error_response(ErrorCode.NOT_FOUND, "App 不存在。", status=HTTPStatus.NOT_FOUND)
    if not can_manage_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner 可以维护该 App 管理范围策略。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def _policy_payload(app: App) -> ManagedScopePolicyPayload:
    policy = ManagedScopePolicyService.get_app_default_policy(app=app)
    effective = ManagedScopePolicyService.get_effective_policy(app=app)
    if effective is None and policy is not None:
        effective_payload = _inactive_policy_item(policy)
    else:
        effective_payload = _effective_policy_item(effective) if effective is not None else None
    return {
        "managed_scope_policy": _policy_item(policy) if policy is not None else None,
        "effective_managed_scope_policy": effective_payload,
    }


def _policy_item(policy: ManagedScopePolicy) -> ManagedScopePolicyPayload:
    return {
        "id": policy.id,
        "target_type": policy.target_type,
        "target_id": policy.target_id,
        "scope": policy.scope,
        "resolver": policy.resolver,
        "enabled": policy.enabled,
    }


def _effective_policy_item(policy: EffectiveManagedScopePolicy) -> ManagedScopePolicyPayload:
    return {
        "resolver": policy.resolver,
        "enabled": policy.policy.enabled,
        "source": policy.source,
        "inherited_from": policy.inherited_from,
        "health_status": "healthy",
        "health_message": "管理范围策略已配置。",
    }


def _inactive_policy_item(policy: ManagedScopePolicy) -> ManagedScopePolicyPayload:
    return {
        "resolver": policy.resolver,
        "enabled": policy.enabled,
        "source": MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
        "inherited_from": None,
        "health_status": "disabled",
        "health_message": "应用默认管理范围策略不启用。",
    }


def _validation_error_response(
    message: str,
    details: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        message,
        details,
        status=HTTPStatus.BAD_REQUEST,
    )


def _record_managed_scope_policy_updated(
    *,
    app: App,
    actor: ConsoleActor,
    resolver: str,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor.user_id,
            action="managed_scope_policy_updated",
            target_type="app",
            target_id=str(app.id),
            metadata={
                "app_key": app.app_key,
                "scope": MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
                "resolver": resolver,
            },
        ),
    )

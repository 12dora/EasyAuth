from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.applications.integration_settings import (
    INTEGRATION_SETTINGS_SINGLETON_ID,
    DingTalkRuntimeConfig,
    IntegrationSettings,
    authentik_runtime_config,
    dingtalk_runtime_config,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.net import InsecureUrlError, require_secure_url
from easyauth.integrations.dingtalk.api_client import invalidate_access_token

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

AUTHENTIK_BASE_URL_INVALID_MESSAGE: Final = "authentik_base_url 必须是 http(s) URL 或留空。"
NOTIFY_CHANNEL_REQUIRED_MESSAGE: Final = (
    "工作通知与服务号机器人不能同时关闭, 至少保留一个通知渠道。"
)


class IntegrationSettingsPatch(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    # 默认值仅供 Pydantic 构造模型; 字段是否出现在 PATCH 中由 model_fields_set 判定。
    authentik_base_url: str = Field(default="", max_length=512)
    authentik_api_token: str = Field(default="", max_length=512)
    dingtalk_app_key: str = Field(default="", max_length=128)
    dingtalk_app_secret: str = Field(default="", max_length=512)
    dingtalk_agent_id: str = Field(default="", max_length=64)
    dingtalk_notify_app_key: str = Field(default="", max_length=128)
    dingtalk_notify_app_secret: str = Field(default="", max_length=512)
    dingtalk_notify_agent_id: str = Field(default="", max_length=64)
    dingtalk_notify_work_notice_enabled: bool = True
    dingtalk_notify_robot_enabled: bool = True

    @field_validator("authentik_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized:
            # 管理 token 走 Authorization: Bearer, base_url 必须 https(仅本地 localhost 允许 http)。
            try:
                require_secure_url(normalized, allow_local_http=True)
            except InsecureUrlError as error:
                raise ValueError(AUTHENTIK_BASE_URL_INVALID_MESSAGE) from error
        return normalized

    @field_validator(
        "authentik_api_token",
        "dingtalk_app_key",
        "dingtalk_app_secret",
        "dingtalk_agent_id",
        "dingtalk_notify_app_key",
        "dingtalk_notify_app_secret",
        "dingtalk_notify_agent_id",
    )
    @classmethod
    def normalize_string(cls, value: str) -> str:
        return value.strip()


def console_integration_settings(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        return _settings_response()
    if request.method == "PATCH":
        return _update_settings(request, actor_id=actor_id)
    return method_not_allowed_response()


def _update_settings(request: HttpRequest, *, actor_id: str) -> JsonResponse:
    try:
        payload = IntegrationSettingsPatch.model_validate_json(request.body)
    except ValidationError as exc:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求参数无效。",
            {"errors": str(exc)},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    fields_set = payload.model_fields_set
    if not fields_set:
        return _settings_response()

    with transaction.atomic():
        row, _created = IntegrationSettings.objects.select_for_update().get_or_create(
            pk=INTEGRATION_SETTINGS_SINGLETON_ID,
        )
        # 必须在锁内读取当前生效凭证, 避免并发 PATCH 失效另一个请求之前的陈旧缓存键。
        previous_dingtalk = dingtalk_runtime_config()
        applied = _apply_settings_patch(row, payload)
        if not row.dingtalk_notify_work_notice_enabled and not row.dingtalk_notify_robot_enabled:
            # 两个钉钉通知渠道同时关闭等于通知彻底失效, 属于无效配置: 直接拒绝并回滚。
            transaction.set_rollback(True)
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                NOTIFY_CHANNEL_REQUIRED_MESSAGE,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        row.updated_by = actor_id
        row.save(update_fields=[*applied.update_fields, "updated_by", "updated_at"])
        _record_settings_update(
            actor_id=actor_id,
            base_url=row.authentik_base_url,
            api_token_changed=applied.api_token_changed,
            dingtalk_secret_changed=applied.dingtalk_secret_changed,
            notify_secret_changed=applied.notify_secret_changed,
        )
        _invalidate_changed_dingtalk_tokens(previous_dingtalk)
    return _settings_response()


@dataclass(frozen=True, slots=True)
class _SettingsPatchResult:
    update_fields: tuple[str, ...]
    api_token_changed: bool
    dingtalk_secret_changed: bool
    notify_secret_changed: bool


def _apply_settings_patch(
    row: IntegrationSettings,
    payload: IntegrationSettingsPatch,
) -> _SettingsPatchResult:
    fields_set = payload.model_fields_set
    update_fields: list[str] = []
    if "authentik_base_url" in fields_set:
        row.authentik_base_url = payload.authentik_base_url
        update_fields.append("authentik_base_url")
    api_token_changed = False
    if "authentik_api_token" in fields_set:
        api_token_changed = payload.authentik_api_token != row.authentik_api_token
        row.authentik_api_token = payload.authentik_api_token
        update_fields.append("authentik_api_token")
    dingtalk = _apply_dingtalk_fields(row, payload, update_fields)
    notify = _apply_notify_fields(row, payload, update_fields)
    return _SettingsPatchResult(
        update_fields=tuple(update_fields),
        api_token_changed=api_token_changed,
        dingtalk_secret_changed=dingtalk.secret_changed,
        notify_secret_changed=notify.secret_changed,
    )


@dataclass(frozen=True, slots=True)
class _CredentialPatchFlags:
    secret_changed: bool


def _apply_dingtalk_fields(
    row: IntegrationSettings,
    payload: IntegrationSettingsPatch,
    update_fields: list[str],
) -> _CredentialPatchFlags:
    fields_set = payload.model_fields_set
    secret_changed = False
    if "dingtalk_app_key" in fields_set:
        row.dingtalk_app_key = payload.dingtalk_app_key
        update_fields.append("dingtalk_app_key")
    if "dingtalk_app_secret" in fields_set:
        secret_changed = payload.dingtalk_app_secret != row.dingtalk_app_secret
        row.dingtalk_app_secret = payload.dingtalk_app_secret
        update_fields.append("dingtalk_app_secret")
    if "dingtalk_agent_id" in fields_set:
        row.dingtalk_agent_id = payload.dingtalk_agent_id
        update_fields.append("dingtalk_agent_id")
    return _CredentialPatchFlags(secret_changed=secret_changed)


def _apply_notify_fields(
    row: IntegrationSettings,
    payload: IntegrationSettingsPatch,
    update_fields: list[str],
) -> _CredentialPatchFlags:
    fields_set = payload.model_fields_set
    secret_changed = False
    if "dingtalk_notify_app_key" in fields_set:
        row.dingtalk_notify_app_key = payload.dingtalk_notify_app_key
        update_fields.append("dingtalk_notify_app_key")
    if "dingtalk_notify_app_secret" in fields_set:
        secret_changed = payload.dingtalk_notify_app_secret != row.dingtalk_notify_app_secret
        row.dingtalk_notify_app_secret = payload.dingtalk_notify_app_secret
        update_fields.append("dingtalk_notify_app_secret")
    if "dingtalk_notify_agent_id" in fields_set:
        row.dingtalk_notify_agent_id = payload.dingtalk_notify_agent_id
        update_fields.append("dingtalk_notify_agent_id")
    if "dingtalk_notify_work_notice_enabled" in fields_set:
        row.dingtalk_notify_work_notice_enabled = payload.dingtalk_notify_work_notice_enabled
        update_fields.append("dingtalk_notify_work_notice_enabled")
    if "dingtalk_notify_robot_enabled" in fields_set:
        row.dingtalk_notify_robot_enabled = payload.dingtalk_notify_robot_enabled
        update_fields.append("dingtalk_notify_robot_enabled")
    return _CredentialPatchFlags(secret_changed=secret_changed)


def _token_fingerprint(app_key: str, app_secret: str) -> tuple[str, str]:
    return (app_key, app_secret)


def _invalidate_changed_dingtalk_tokens(previous: DingTalkRuntimeConfig) -> None:
    current = dingtalk_runtime_config()
    stale: set[tuple[str, str]] = set()
    previous_main = _token_fingerprint(previous.app_key, previous.app_secret)
    current_main = _token_fingerprint(current.app_key, current.app_secret)
    previous_notify = _token_fingerprint(previous.notify.app_key, previous.notify.app_secret)
    current_notify = _token_fingerprint(current.notify.app_key, current.notify.app_secret)
    if previous_main != current_main:
        stale.add(previous_main)
    if previous_notify != current_notify:
        stale.add(previous_notify)
    for app_key, app_secret in stale:
        _schedule_token_invalidation(app_key, app_secret)


def _schedule_token_invalidation(app_key: str, app_secret: str) -> None:
    if not app_key or not app_secret:
        return

    def _invalidate() -> None:
        invalidate_access_token(app_key=app_key, app_secret=app_secret)

    transaction.on_commit(_invalidate)


def _settings_response() -> JsonResponse:
    config = authentik_runtime_config()
    dingtalk = dingtalk_runtime_config()
    row = IntegrationSettings.objects.filter(pk=1).first()
    payload: dict[str, JsonValue] = {
        "authentik_base_url_override": row.authentik_base_url if row is not None else "",
        "authentik_base_url_effective": config.base_url,
        "authentik_base_url_source": config.base_url_source,
        "authentik_api_token_configured": bool(config.api_token),
        "authentik_api_token_source": config.api_token_source,
        "authentik_source_slug": config.source_slug,
        "dingtalk_app_key": dingtalk.app_key,
        "dingtalk_app_secret_configured": bool(dingtalk.app_secret),
        "dingtalk_agent_id": dingtalk.agent_id,
        "dingtalk_notify_app_key": row.dingtalk_notify_app_key if row is not None else "",
        "dingtalk_notify_app_secret_configured": bool(row.dingtalk_notify_app_secret)
        if row is not None
        else False,
        "dingtalk_notify_agent_id": row.dingtalk_notify_agent_id if row is not None else "",
        "dingtalk_notify_work_notice_enabled": True
        if row is None
        else row.dingtalk_notify_work_notice_enabled,
        "dingtalk_notify_robot_enabled": True
        if row is None
        else row.dingtalk_notify_robot_enabled,
        "updated_at": datetime_value(row.updated_at) if row is not None else None,
        "updated_by": row.updated_by if row is not None else "",
    }
    return json_response(payload)


def _record_settings_update(
    *,
    actor_id: str,
    base_url: str,
    api_token_changed: bool,
    dingtalk_secret_changed: bool,
    notify_secret_changed: bool,
) -> None:
    # 审计记录不得包含 token/secret 明文。
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="integration_settings_updated",
            target_type="integration_settings",
            target_id="authentik",
            metadata={
                "authentik_base_url": base_url,
                "api_token_changed": api_token_changed,
                "dingtalk_secret_changed": dingtalk_secret_changed,
                "dingtalk_notify_secret_changed": notify_secret_changed,
            },
        ),
    )

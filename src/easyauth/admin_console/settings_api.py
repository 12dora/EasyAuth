from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.authz import require_superuser
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.applications.integration_settings import (
    INTEGRATION_SETTINGS_SINGLETON_ID,
    IntegrationSettings,
    authentik_runtime_config,
    dingtalk_runtime_config,
)
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.net import InsecureUrlError, require_secure_url
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiClient,
    DingTalkApiError,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

AUTHENTIK_BASE_URL_INVALID_MESSAGE: Final = "authentik_base_url 必须是 http(s) URL 或留空。"


class IntegrationSettingsPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    authentik_base_url: str = Field(default="", max_length=512)
    # None 表示保持现有 token 不变; 空字符串表示清除覆盖值。
    authentik_api_token: str | None = Field(default=None, max_length=512)
    dingtalk_app_key: str | None = Field(default=None, max_length=128)
    # 与 authentik_api_token 同语义: None 保持不变, 空串清除。
    dingtalk_app_secret: str | None = Field(default=None, max_length=512)
    dingtalk_agent_id: str | None = Field(default=None, max_length=64)

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

    @field_validator("authentik_api_token")
    @classmethod
    def normalize_api_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


def console_integration_settings(request: HttpRequest) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method == "GET":
        return _settings_response()
    if request.method == "PUT":
        return _update_settings(request, actor_id=actor_id)
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "请求方法无效。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def _update_settings(request: HttpRequest, *, actor_id: str) -> JsonResponse:
    try:
        payload = IntegrationSettingsPayload.model_validate_json(request.body)
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
        update_fields: list[str] = []
        if "authentik_base_url" in fields_set:
            row.authentik_base_url = payload.authentik_base_url
            update_fields.append("authentik_base_url")
        api_token_changed = False
        if "authentik_api_token" in fields_set and payload.authentik_api_token is not None:
            api_token_changed = payload.authentik_api_token != row.authentik_api_token
            row.authentik_api_token = payload.authentik_api_token
            update_fields.append("authentik_api_token")
        dingtalk_secret_changed = False
        if "dingtalk_app_key" in fields_set and payload.dingtalk_app_key is not None:
            row.dingtalk_app_key = payload.dingtalk_app_key.strip()
            update_fields.append("dingtalk_app_key")
        if "dingtalk_app_secret" in fields_set and payload.dingtalk_app_secret is not None:
            dingtalk_secret_changed = payload.dingtalk_app_secret != row.dingtalk_app_secret
            row.dingtalk_app_secret = payload.dingtalk_app_secret.strip()
            update_fields.append("dingtalk_app_secret")
        if "dingtalk_agent_id" in fields_set and payload.dingtalk_agent_id is not None:
            row.dingtalk_agent_id = payload.dingtalk_agent_id.strip()
            update_fields.append("dingtalk_agent_id")
        row.updated_by = actor_id
        row.save(update_fields=[*update_fields, "updated_by", "updated_at"])
        _record_settings_update(
            actor_id=actor_id,
            base_url=row.authentik_base_url,
            api_token_changed=api_token_changed,
            dingtalk_secret_changed=dingtalk_secret_changed,
        )
    return _settings_response()


def console_dingtalk_connectivity_test(request: HttpRequest) -> JsonResponse:
    # 连通性测试: 用当前生效凭证取一次 accessToken; 不落任何业务数据。
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "请求方法无效。",
            status=HTTPStatus.METHOD_NOT_ALLOWED,
        )
    try:
        _ = DingTalkApiClient.from_settings().get_access_token()
    except DingTalkApiError as error:
        _record_dingtalk_test(actor_id=actor_id, ok=False, error=str(error))
        return json_response({"ok": False, "message": str(error)})
    _record_dingtalk_test(actor_id=actor_id, ok=True, error="")
    return json_response({"ok": True, "message": "钉钉凭证有效, 已成功获取访问令牌。"})


def _record_dingtalk_test(*, actor_id: str, ok: bool, error: str) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="admin",
            actor_id=actor_id,
            action="dingtalk_connectivity_tested",
            target_type="integration_settings",
            target_id="dingtalk",
            metadata={"ok": ok, "error": error},
        ),
    )


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
            },
        ),
    )

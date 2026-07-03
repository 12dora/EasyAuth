from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, ClassVar, Final

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from easyauth.admin_console.api_responses import error_response, json_response
from easyauth.admin_console.authz import require_superuser
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.applications.integration_settings import (
    IntegrationSettings,
    authentik_runtime_config,
)
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

AUTHENTIK_BASE_URL_INVALID_MESSAGE: Final = "authentik_base_url 必须是 http(s) URL 或留空。"


class IntegrationSettingsPayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    authentik_base_url: str = Field(default="", max_length=512)
    # None 表示保持现有 token 不变; 空字符串表示清除覆盖值。
    authentik_api_token: str | None = Field(default=None, max_length=512)

    @field_validator("authentik_base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if normalized and not normalized.startswith(("http://", "https://")):
            raise ValueError(AUTHENTIK_BASE_URL_INVALID_MESSAGE)
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
    row = IntegrationSettings.load()
    row.authentik_base_url = payload.authentik_base_url
    api_token_changed = False
    if payload.authentik_api_token is not None:
        api_token_changed = payload.authentik_api_token != row.authentik_api_token
        row.authentik_api_token = payload.authentik_api_token
    row.updated_by = actor_id
    row.save()
    _record_settings_update(
        actor_id=actor_id,
        base_url=payload.authentik_base_url,
        api_token_changed=api_token_changed,
    )
    return _settings_response()


def _settings_response() -> JsonResponse:
    config = authentik_runtime_config()
    row = IntegrationSettings.objects.filter(pk=1).first()
    payload: dict[str, JsonValue] = {
        "authentik_base_url_override": row.authentik_base_url if row is not None else "",
        "authentik_base_url_effective": config.base_url,
        "authentik_base_url_source": config.base_url_source,
        "authentik_api_token_configured": bool(config.api_token),
        "authentik_api_token_source": config.api_token_source,
        "authentik_source_slug": config.source_slug,
        "updated_at": datetime_value(row.updated_at) if row is not None else None,
        "updated_by": row.updated_by if row is not None else "",
    }
    return json_response(payload)


def _record_settings_update(*, actor_id: str, base_url: str, api_token_changed: bool) -> None:
    # 审计记录不得包含 token 明文。
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
            },
        ),
    )

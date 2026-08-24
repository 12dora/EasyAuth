"""处理控制台交接 v2 的应用能力读取、声明与同步。"""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_responses import (
    error_response,
    json_response,
    method_not_allowed_response,
)
from easyauth.admin_console.authz import require_superuser
from easyauth.admin_console.auto_onboarding_api import (
    AutoOnboardingError,
    repull_app_descriptor,
)
from easyauth.admin_console.handover_v2_support import not_found
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode
from easyauth.applications.handover_capability import declare_handover_none
from easyauth.applications.manifest_import import ManifestVersionConflictError
from easyauth.applications.models import App
from easyauth.applications.permission_templates import PermissionTemplateImportError
from easyauth.webhooks.models import AppWebhookConfig


class DeclareNonePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    reason: str = Field(min_length=1, max_length=2000)


def console_handover_capability(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return not_found()
    if request.method == "GET":
        config = AppWebhookConfig.objects.filter(app=app).first()
        return json_response(
            {
                "handover_capability": app.handover_capability,
                "handover_asset_types": app.handover_asset_types or [],
                "handover_url": config.handover_url if config else "",
                "declared_by": app.handover_capability_declared_by,
                "declared_at": datetime_value(app.handover_capability_declared_at),
                "synced_at": datetime_value(app.handover_capability_synced_at),
            },
        )
    if request.method == "POST":
        try:
            payload = DeclareNonePayload.model_validate_json(request.body)
        except ValidationError as exc:
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                "参数无效。",
                {"errors": str(exc)},
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )
        app = declare_handover_none(app, actor_id=actor_id, reason=payload.reason)
        return json_response(
            {
                "handover_capability": app.handover_capability,
                "handover_asset_types": [],
                "handover_url": "",
                "declared_by": app.handover_capability_declared_by,
                "declared_at": datetime_value(app.handover_capability_declared_at),
                "synced_at": datetime_value(app.handover_capability_synced_at),
            },
        )
    return method_not_allowed_response()


def console_handover_capability_sync(request: HttpRequest, app_key: str) -> JsonResponse:
    match require_superuser(request):
        case str() as actor_id:
            pass
        case JsonResponse() as response:
            return response
    if request.method != "POST":
        return method_not_allowed_response()
    return _sync_handover_capability(app_key, actor_id=actor_id)


def _sync_handover_capability(app_key: str, *, actor_id: str) -> JsonResponse:
    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return not_found()
    try:
        _ = repull_app_descriptor(app=app, actor_id=actor_id)
    except AutoOnboardingError as exc:
        return error_response(exc.code, exc.message, status=exc.status)
    except ManifestVersionConflictError as exc:
        return error_response(
            ErrorCode.CONFLICT,
            str(exc),
            status=HTTPStatus.CONFLICT,
        )
    except PermissionTemplateImportError as exc:
        return error_response(
            ErrorCode.SEMANTIC_VALIDATION_ERROR,
            f"manifest 导入失败: {exc.message}",
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    except Exception as exc:  # noqa: BLE001 - 网络/解析失败显式 502
        return error_response(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            f"descriptor 同步失败: {exc}",
            status=HTTPStatus.BAD_GATEWAY,
        )
    app.refresh_from_db()
    config = AppWebhookConfig.objects.filter(app=app).first()
    return json_response(
        {
            "handover_capability": app.handover_capability,
            "handover_asset_types": app.handover_asset_types or [],
            "handover_url": config.handover_url if config else "",
            "declared_by": app.handover_capability_declared_by,
            "declared_at": datetime_value(app.handover_capability_declared_at),
            "synced_at": datetime_value(app.handover_capability_synced_at),
        },
    )

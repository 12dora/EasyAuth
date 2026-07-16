from __future__ import annotations

import json
from http import HTTPStatus
from typing import Final, cast
from uuid import UUID

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.permission_query_auth import authenticate_permission_query_token
from easyauth.api.responses import error_response, json_response
from easyauth.applications.capabilities import (
    app_capability_config,
    app_capability_enabled,
    credential_capability_enabled,
)
from easyauth.applications.models import CAPABILITY_NOTIFY, App
from easyauth.applications.services import AppPrincipal
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.rate_limit import client_ip, over_limit, rate_limit_exceeded
from easyauth.notify.models import NotifyMessage, NotifyRecipient
from easyauth.notify.services import (
    DEFAULT_DEEPLINK_TITLE,
    NotifyAcceptError,
    accept_notify_message,
)

_AUTHENTICATION_FAILED_MESSAGE: Final = "应用认证凭据无效。"
_PERMISSION_DENIED_MESSAGE: Final = "应用无权查询该资源。"
_NOTIFY_CAPABILITY_DENIED_MESSAGE: Final = "应用未开通通知能力。"
_TOO_MANY_REQUESTS_MESSAGE: Final = "请求过于频繁, 请稍后再试。"
_MESSAGE_NOT_FOUND_MESSAGE: Final = "通知消息不存在。"
_INVALID_JSON_MESSAGE: Final = "请求体必须是 JSON 对象。"
_AUTH_SCHEME: Final = "Bearer"
_AUTH_FAIL_LIMIT: Final = 30
_AUTH_FAIL_WINDOW_SECONDS: Final = 300
_STATUS_RATE_LIMIT: Final = 240
_STATUS_RATE_WINDOW_SECONDS: Final = 60
_POST_RATE_WINDOW_SECONDS: Final = 60
_DEFAULT_RATE_PER_MINUTE: Final = 60
_RETRY_AFTER_HEADER: Final = "Retry-After"
_AUTH_FAIL_NAMESPACE: Final = "notify-authfail"
_POST_RATE_NAMESPACE: Final = "notify-post-rate"
_STATUS_RATE_NAMESPACE: Final = "notify-status-rate"
_NOTIFY_ACCEPTED_ACTION: Final = "app_notify_accepted"
_NOTIFY_REJECTED_ACTION: Final = "app_notify_rejected"


# Bearer 鉴权的服务端到服务端接口, 无浏览器会话, 豁免 CSRF(对齐 approval_views 的 POST 端点)。
@csrf_exempt
@require_http_methods(["POST"])
def notify_messages_create(request: HttpRequest, app_key: str) -> JsonResponse:
    match _authenticate_notify_capability(request, app_key):
        case (App() as app, AppPrincipal() as principal):
            pass
        case JsonResponse() as response:
            return response

    rate_limit = _post_rate_per_minute(app.id)
    if rate_limit_exceeded(
        _POST_RATE_NAMESPACE,
        app.id,
        limit=rate_limit,
        window_seconds=_POST_RATE_WINDOW_SECONDS,
    ):
        return _too_many_requests_response(_POST_RATE_WINDOW_SECONDS)

    body = _json_object_body(request)
    if isinstance(body, JsonResponse):
        return body

    try:
        result = accept_notify_message(
            app=app,
            recipients=_as_string_list(body.get("recipients")),
            template=_as_str(body.get("template")),
            title=_as_str(body.get("title")),
            content=_as_str(body.get("content")),
            deeplink_url=_as_str(body.get("deeplink_url")),
            deeplink_title=_as_str(body.get("deeplink_title")) or DEFAULT_DEEPLINK_TITLE,
            dedup_key=_as_str(body.get("dedup_key")),
            biz_tag=_as_str(body.get("biz_tag")),
            requested_credential_type=principal.credential_type,
            requested_credential_id=principal.credential_id,
        )
    except NotifyAcceptError as exc:
        return _accept_error_response(principal=principal, exc=exc, body=body)
    except TypeError:
        _record_notify_rejected(
            principal=principal,
            error_code=ErrorCode.VALIDATION_ERROR.value,
            recipient_count=_recipient_count_from_body(body),
        )
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            "recipients 必须为 1~500 个用户引用。",
            {"field": "recipients"},
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    _ = AuditService.record(
        AuditRecord(
            actor_type="app",
            actor_id=principal.app_key,
            action=_NOTIFY_ACCEPTED_ACTION,
            target_type="notify_message",
            target_id=str(result.message.id),
            metadata={
                "template": result.message.template,
                "biz_tag": result.message.biz_tag,
                "recipient_total": result.recipient_total,
                "dedup_hit": not result.accepted,
                "credential_id": principal.credential_id,
            },
        ),
    )
    status = HTTPStatus.ACCEPTED if result.accepted else HTTPStatus.OK
    payload: dict[str, JsonValue] = {
        "message_id": str(result.message.id),
        "accepted": result.accepted,
        "status": result.message.status,
        "recipient_total": result.recipient_total,
        "recipient_rejected": result.recipient_rejected,
    }
    return json_response(payload, status=status)


@require_http_methods(["GET"])
def notify_message_detail(
    request: HttpRequest,
    app_key: str,
    message_id: str,
) -> JsonResponse:
    match _authenticate_notify_capability(request, app_key):
        case (App() as app, AppPrincipal() as principal):
            pass
        case JsonResponse() as response:
            return response

    if rate_limit_exceeded(
        _STATUS_RATE_NAMESPACE,
        principal.credential_id,
        limit=_STATUS_RATE_LIMIT,
        window_seconds=_STATUS_RATE_WINDOW_SECONDS,
    ):
        return _too_many_requests_response(_STATUS_RATE_WINDOW_SECONDS)

    try:
        message_uuid = UUID(str(message_id))
    except ValueError:
        return error_response(
            ErrorCode.NOT_FOUND,
            _MESSAGE_NOT_FOUND_MESSAGE,
            status=HTTPStatus.NOT_FOUND,
        )

    message = NotifyMessage.objects.filter(id=message_uuid, app=app).first()
    if message is None:
        return error_response(
            ErrorCode.NOT_FOUND,
            _MESSAGE_NOT_FOUND_MESSAGE,
            status=HTTPStatus.NOT_FOUND,
        )

    recipient_items: list[JsonValue] = [
        _recipient_payload(row)
        for row in NotifyRecipient.objects.filter(message=message)
        .select_related("user")
        .order_by("id")
    ]
    payload: dict[str, JsonValue] = {
        "message_id": str(message.id),
        "status": message.status,
        "template": message.template,
        "biz_tag": message.biz_tag,
        "dedup_key": message.dedup_key,
        "created_at": datetime_value(message.created_at),
        "completed_at": datetime_value(message.completed_at),
        "recipient_total": message.recipient_total,
        "recipient_sent": message.recipient_sent,
        "recipient_failed": message.recipient_failed,
        "recipients": recipient_items,
    }
    return json_response(payload)


def _recipient_payload(row: NotifyRecipient) -> JsonValue:
    user_id = row.user.authentik_user_id if row.user is not None else None
    item: dict[str, JsonValue] = {
        "raw_ref": row.raw_ref,
        "user_id": user_id,
        "dingtalk_user_id": row.dingtalk_userid or None,
        "status": row.status,
        "error_code": row.error_code,
        "error": row.error,
        "sent_at": datetime_value(row.sent_at),
        "delivered_at": datetime_value(row.delivered_at),
    }
    return item


def _authenticate_notify_capability(
    request: HttpRequest,
    app_key: str,
) -> tuple[App, AppPrincipal] | JsonResponse:
    match _authenticate_and_authfail_throttle(request):
        case AppPrincipal() as principal:
            pass
        case JsonResponse() as response:
            return response
    if principal.app_key != app_key:
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            _PERMISSION_DENIED_MESSAGE,
            status=HTTPStatus.FORBIDDEN,
        )
    app = App.objects.filter(id=principal.app_id, is_active=True).first()
    if app is None:
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            _AUTHENTICATION_FAILED_MESSAGE,
            status=HTTPStatus.UNAUTHORIZED,
        )
    if not app_capability_enabled(app.id, CAPABILITY_NOTIFY) or not credential_capability_enabled(
        principal,
        CAPABILITY_NOTIFY,
    ):
        _record_notify_rejected(
            principal=principal,
            error_code=ErrorCode.PERMISSION_DENIED.value,
            recipient_count=0,
        )
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            _NOTIFY_CAPABILITY_DENIED_MESSAGE,
            status=HTTPStatus.FORBIDDEN,
        )
    return app, principal


def _authenticate_and_authfail_throttle(
    request: HttpRequest,
) -> AppPrincipal | JsonResponse:
    ip = client_ip(request)
    if over_limit(_AUTH_FAIL_NAMESPACE, ip, limit=_AUTH_FAIL_LIMIT):
        return _too_many_requests_response(_AUTH_FAIL_WINDOW_SECONDS)
    match _authenticate_app(request):
        case AppPrincipal() as principal:
            return principal
        case JsonResponse() as response:
            _ = rate_limit_exceeded(
                _AUTH_FAIL_NAMESPACE,
                ip,
                limit=_AUTH_FAIL_LIMIT,
                window_seconds=_AUTH_FAIL_WINDOW_SECONDS,
            )
            return response


def _authenticate_app(request: HttpRequest) -> AppPrincipal | JsonResponse:
    token = _bearer_token_from_request(request)
    if token is None:
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            _AUTHENTICATION_FAILED_MESSAGE,
            status=HTTPStatus.UNAUTHORIZED,
        )
    try:
        return authenticate_permission_query_token(token)
    except AuthenticationFailed:
        return error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            _AUTHENTICATION_FAILED_MESSAGE,
            status=HTTPStatus.UNAUTHORIZED,
        )
    except PermissionDenied:
        return error_response(
            ErrorCode.PERMISSION_DENIED,
            _PERMISSION_DENIED_MESSAGE,
            status=HTTPStatus.FORBIDDEN,
        )


def _bearer_token_from_request(request: HttpRequest) -> str | None:
    raw_header: str | None = request.META.get("HTTP_AUTHORIZATION")
    if raw_header is None:
        return None
    scheme, separator, token = raw_header.partition(" ")
    if not separator:
        return None
    if scheme.lower() != _AUTH_SCHEME.lower():
        return None
    if not token:
        return None
    return token


def _post_rate_per_minute(app_id: int) -> int:
    config = app_capability_config(app_id, CAPABILITY_NOTIFY)
    raw = config.get("rate_per_minute")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    default = getattr(
        settings,
        "EASYAUTH_NOTIFY_DEFAULT_RATE_PER_MINUTE",
        _DEFAULT_RATE_PER_MINUTE,
    )
    if isinstance(default, int) and not isinstance(default, bool) and default > 0:
        return default
    return _DEFAULT_RATE_PER_MINUTE


def _json_object_body(request: HttpRequest) -> dict[str, object] | JsonResponse:
    try:
        parsed = cast("object", json.loads(request.body.decode("utf-8") or "{}"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            _INVALID_JSON_MESSAGE,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    if not isinstance(parsed, dict):
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            _INVALID_JSON_MESSAGE,
            status=HTTPStatus.UNPROCESSABLE_ENTITY,
        )
    return cast("dict[str, object]", parsed)


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        message = "recipients 必须为 1~500 个用户引用。"
        raise TypeError(message)
    result: list[str] = []
    for item in cast("list[object]", value):
        if not isinstance(item, str):
            message = "recipients 必须为 1~500 个用户引用。"
            raise TypeError(message)
        result.append(item)
    return result


def _recipient_count_from_body(body: dict[str, object]) -> int:
    raw_recipients = body.get("recipients")
    if not isinstance(raw_recipients, list):
        return 0
    return len(cast("list[object]", raw_recipients))


def _record_notify_rejected(
    *,
    principal: AppPrincipal,
    error_code: str,
    recipient_count: int,
) -> None:
    _ = AuditService.record(
        AuditRecord(
            actor_type="app",
            actor_id=principal.app_key,
            action=_NOTIFY_REJECTED_ACTION,
            target_type="notify_message",
            target_id=principal.app_key,
            metadata={
                "error_code": error_code,
                "recipient_count": recipient_count,
                "credential_id": principal.credential_id,
            },
        ),
    )


def _accept_error_response(
    *,
    principal: AppPrincipal,
    exc: NotifyAcceptError,
    body: dict[str, object],
) -> JsonResponse:
    error_code = {
        "conflict": ErrorCode.CONFLICT.value,
        "throttled": ErrorCode.THROTTLED.value,
        "validation_error": ErrorCode.VALIDATION_ERROR.value,
    }.get(exc.kind, ErrorCode.VALIDATION_ERROR.value)
    _record_notify_rejected(
        principal=principal,
        error_code=error_code,
        recipient_count=_recipient_count_from_body(body),
    )
    match exc.kind:
        case "conflict":
            return error_response(
                ErrorCode.CONFLICT,
                exc.message,
                status=HTTPStatus.CONFLICT,
            )
        case "throttled":
            retry_after = exc.retry_after_seconds or _seconds_until_next_day_fallback()
            return _too_many_requests_response(retry_after, message=exc.message)
        case "validation_error":
            details: dict[str, JsonValue] = {}
            if exc.field:
                details["field"] = exc.field
            return error_response(
                ErrorCode.VALIDATION_ERROR,
                exc.message,
                details or None,
                status=HTTPStatus.UNPROCESSABLE_ENTITY,
            )


def _seconds_until_next_day_fallback() -> int:
    return 3600


def _too_many_requests_response(
    retry_after_seconds: int,
    *,
    message: str = _TOO_MANY_REQUESTS_MESSAGE,
) -> JsonResponse:
    response = error_response(
        ErrorCode.THROTTLED,
        message,
        status=HTTPStatus.TOO_MANY_REQUESTS,
    )
    response[_RETRY_AFTER_HEADER] = str(max(1, retry_after_seconds))
    return response

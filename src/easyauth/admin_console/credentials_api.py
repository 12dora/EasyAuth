from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from django.http import HttpRequest, JsonResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from easyauth.admin_console.api_payloads import list_payload
from easyauth.admin_console.credentials import (
    CredentialActor,
    CredentialOperationError,
    create_oauth_client_for_console,
    create_static_token_for_console,
    rotate_static_token_for_console,
)
from easyauth.admin_console.credentials_api_payloads import (
    credential_items,
    credential_secret_payload,
    oauth_client_item,
    static_credential_item,
)
from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App, AppCredential, OAuthClientBinding
from easyauth.applications.ownership import ConsoleActor, can_manage_app, can_view_app

type CredentialsApiResult = ConsoleActor | JsonResponse
type AppApiResult = App | JsonResponse


class CredentialCreatePayload(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=128)


def console_credentials(request: HttpRequest, app_key: str) -> JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    if request.method != "GET":
        return _method_not_allowed_response()

    return _json_response(list_payload(credential_items(app)))


def console_static_token_create(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed_response()

    match credential_write_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    match _create_payload(request):
        case CredentialCreatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response

    one_time_secret = create_static_token_for_console(
        app=app,
        name=payload.name,
        actor=CredentialActor(actor_id=actor.user_id),
    )
    credential = AppCredential.objects.get(id=one_time_secret.credential_id)
    return _json_response(
        credential_secret_payload(static_credential_item(credential), one_time_secret),
        status=HTTPStatus.CREATED,
    )


def console_static_token_rotate(
    request: HttpRequest,
    app_key: str,
    credential_id: int,
) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed_response()

    match credential_write_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    try:
        one_time_secret = rotate_static_token_for_console(
            app=app,
            credential_id=credential_id,
            actor=CredentialActor(actor_id=actor.user_id),
        )
    except CredentialOperationError:
        return _not_found_response()
    credential = AppCredential.objects.get(id=one_time_secret.credential_id)
    return _json_response(
        credential_secret_payload(static_credential_item(credential), one_time_secret),
        status=HTTPStatus.CREATED,
    )


def console_oauth_client_create(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method != "POST":
        return _method_not_allowed_response()

    match credential_write_context(request, app_key):
        case (App() as app, ConsoleActor() as actor):
            pass
        case JsonResponse() as response:
            return response

    match _create_payload(request):
        case CredentialCreatePayload() as payload:
            pass
        case JsonResponse() as response:
            return response

    one_time_secret = create_oauth_client_for_console(
        app=app,
        name=payload.name,
        actor=CredentialActor(actor_id=actor.user_id),
    )
    binding = OAuthClientBinding.objects.select_related("oauth_application").get(
        id=one_time_secret.credential_id,
    )
    return _json_response(
        credential_secret_payload(oauth_client_item(binding), one_time_secret),
        status=HTTPStatus.CREATED,
    )


def _create_payload(request: HttpRequest) -> CredentialCreatePayload | JsonResponse:
    try:
        return CredentialCreatePayload.model_validate_json(request.body)
    except ValidationError as error:
        return _error_response(
            ErrorCode.VALIDATION_ERROR,
            "凭据参数无效。",
            {"errors": str(error)},
            status=HTTPStatus.BAD_REQUEST,
        )


def _read_context(request: HttpRequest, app_key: str) -> AppApiResult:
    match _actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None:
        return _not_found_response()
    if not can_view_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 active App owner/developer 可以访问该 App 凭据。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app


def credential_write_context(
    request: HttpRequest,
    app_key: str,
) -> tuple[App, ConsoleActor] | JsonResponse:
    match _read_context(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    actor = _authenticated_actor(request)
    if not can_manage_app(actor, app):
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有 App owner 可以管理凭据。",
            status=HTTPStatus.FORBIDDEN,
        )
    return app, actor


def _actor_from_request(request: HttpRequest) -> CredentialsApiResult:
    user = request.user
    if not user.is_authenticated:
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return _authenticated_actor(request)


def _authenticated_actor(request: HttpRequest) -> ConsoleActor:
    user = request.user
    return ConsoleActor(
        user_id=user.get_username(),
        is_superuser=bool(getattr(user, "is_superuser", False)),
    )


def _method_not_allowed_response() -> JsonResponse:
    return _error_response(
        ErrorCode.VALIDATION_ERROR,
        "不支持的请求方法。",
        status=HTTPStatus.METHOD_NOT_ALLOWED,
    )


def _not_found_response() -> JsonResponse:
    return _error_response(
        ErrorCode.NOT_FOUND,
        "凭据不存在。",
        status=HTTPStatus.NOT_FOUND,
    )


def _error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, JsonValue] | None = None,
    *,
    status: HTTPStatus,
) -> JsonResponse:
    return _json_response(build_error_response(code, message, details), status=status)


def _json_response(
    payload: dict[str, JsonValue] | ErrorResponse,
    *,
    status: HTTPStatus = HTTPStatus.OK,
) -> JsonResponse:
    return JsonResponse(
        payload,
        status=status,
        json_dumps_params={"ensure_ascii": False},
    )

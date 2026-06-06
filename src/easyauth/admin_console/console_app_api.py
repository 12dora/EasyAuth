from __future__ import annotations

from http import HTTPStatus

from django.http import HttpRequest, JsonResponse

from easyauth.api.errors import ErrorCode, ErrorResponse, JsonValue, build_error_response
from easyauth.applications.models import App, AppCredential, OAuthClientBinding
from easyauth.applications.ownership import ConsoleActor, can_view_app
from easyauth.applications.services import APP_CREDENTIAL_STATIC_KIND

type ConsoleAppApiResult = ConsoleActor | JsonResponse
type AppLookupResult = App | JsonResponse


def integration_guide_api(request: HttpRequest, app_key: str) -> JsonResponse:
    match _scoped_app(request, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    return _json_response(
        {
            "app_key": app.app_key,
            "permission_query_endpoint": (
                f"/api/v1/apps/{app.app_key}/users/{{user_id}}/permissions"
            ),
            "credential_modes": _credential_modes(app),
        },
    )


def _scoped_app(request: HttpRequest, app_key: str) -> AppLookupResult:
    match _actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        return _error_response(
            ErrorCode.NOT_FOUND,
            "应用不存在。",
            status=HTTPStatus.NOT_FOUND,
        )
    return app


def _actor_from_request(request: HttpRequest) -> ConsoleAppApiResult:
    user = request.user
    if not user.is_authenticated:
        return _error_response(
            ErrorCode.AUTHENTICATION_FAILED,
            "控制台登录已失效。",
            status=HTTPStatus.UNAUTHORIZED,
        )
    return ConsoleActor(
        user_id=user.get_username(),
        is_superuser=bool(getattr(user, "is_superuser", False)),
    )


def _credential_modes(app: App) -> list[JsonValue]:
    return [
        {
            "mode": "static_token",
            "active_count": AppCredential.objects.filter(
                app=app,
                credential_type=APP_CREDENTIAL_STATIC_KIND,
                is_active=True,
            ).count(),
        },
        {
            "mode": "oauth_client_credentials",
            "active_count": OAuthClientBinding.objects.filter(app=app, is_active=True).count(),
        },
    ]


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

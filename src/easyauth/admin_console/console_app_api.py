from __future__ import annotations

from http import HTTPStatus

from django.http import HttpRequest, JsonResponse

from easyauth.admin_console.api_responses import (
    error_response as _error_response,
)
from easyauth.admin_console.api_responses import (
    json_response as _json_response,
)
from easyauth.admin_console.request_guards import require_console_actor
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppCredential, OAuthClientBinding
from easyauth.applications.ownership import ConsoleActor, can_view_app
from easyauth.applications.services import APP_CREDENTIAL_STATIC_KIND

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
    match require_console_actor(request):
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

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Final, Literal
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    HttpResponseRedirect,
)
from django.shortcuts import render

from easyauth.admin_console.configuration import ConsoleConfigurationError
from easyauth.admin_console.configuration_forms import (
    ConsoleConfigurationFormError,
    handle_configuration_form_post,
)
from easyauth.admin_console.credentials import (
    CredentialActor,
    CredentialOperationError,
    OneTimeSecret,
    create_oauth_client_for_console,
    create_static_token_for_console,
    disable_static_token_for_console,
    rotate_static_token_for_console,
)
from easyauth.admin_console.permission_templates import (
    PermissionTemplateConsoleResult,
    handle_permission_template_post,
)
from easyauth.admin_console.query_tester import (
    PermissionQueryTestResult,
    run_permission_query_test,
)
from easyauth.admin_console.view_data import app_detail_context
from easyauth.applications.models import App
from easyauth.applications.ownership import (
    ConsoleActor,
    can_manage_app,
    can_view_app,
)

CONSOLE_TEMPLATE: Literal["admin_console/app_detail.html"] = "admin_console/app_detail.html"
CONFIG_ACTIONS: Final = frozenset(
    {
        "set_role_permission",
        "create_role",
        "create_permission",
        "create_approval_rule",
    },
)
TEMPLATE_ACTIONS: Final = frozenset({"preview_permission_template", "apply_permission_template"})
CREDENTIAL_ACTIONS: Final = frozenset(
    {
        "create_static_token",
        "rotate_static_token",
        "disable_static_token",
        "create_oauth_client",
    },
)


@dataclass(frozen=True, slots=True)
class _RenderState:
    one_time_secret: OneTimeSecret | None = None
    template_result: PermissionTemplateConsoleResult | None = None
    query_test_result: PermissionQueryTestResult | None = None


def app_detail(request: HttpRequest, app_key: str) -> HttpResponse:
    match _actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case None:
            return _login_redirect(request)

    app = _visible_app(actor, app_key)
    if request.method == "POST":
        return _post_response(request, actor, app)

    return _render_detail(request, actor, app, state=_RenderState())


def _post_response(request: HttpRequest, actor: ConsoleActor, app: App) -> HttpResponse:
    action = request.POST.get("action", "")
    if _action_requires_manage(action) and not can_manage_app(actor, app):
        return HttpResponseForbidden("无权限")
    try:
        post_result = _handle_post(request, actor, app, action=action)
    except (
        ConsoleConfigurationFormError,
        ConsoleConfigurationError,
        CredentialOperationError,
        ValidationError,
        ValueError,
    ):
        return HttpResponse(
            "表单参数无效",
            status=HTTPStatus.BAD_REQUEST,
            content_type="text/plain; charset=utf-8",
        )
    match post_result:
        case OneTimeSecret() as one_time_secret:
            return _render_detail(request, actor, app, state=_RenderState(one_time_secret))
        case PermissionQueryTestResult() as query_test_result:
            return _render_detail(
                request,
                actor,
                app,
                state=_RenderState(query_test_result=query_test_result),
            )
        case PermissionTemplateConsoleResult() as template_result:
            return _render_detail(
                request,
                actor,
                app,
                state=_RenderState(template_result=template_result),
            )
        case None:
            return HttpResponseRedirect(request.path)


def _render_detail(
    request: HttpRequest,
    actor: ConsoleActor,
    app: App,
    *,
    state: _RenderState,
) -> HttpResponse:
    return render(
        request,
        CONSOLE_TEMPLATE,
        app_detail_context(
            actor,
            app,
            one_time_secret=state.one_time_secret,
            template_result=state.template_result,
            query_test_result=state.query_test_result,
        ),
        status=HTTPStatus.OK,
    )


def _handle_post(
    request: HttpRequest,
    actor: ConsoleActor,
    app: App,
    *,
    action: str,
) -> OneTimeSecret | PermissionQueryTestResult | PermissionTemplateConsoleResult | None:
    if action in TEMPLATE_ACTIONS:
        return handle_permission_template_post(
            app=app,
            action=action,
            raw_template=request.POST.get("template_content", ""),
            raw_format=request.POST.get("template_format", ""),
            actor_id=actor.user_id,
        )
    if action in CONFIG_ACTIONS:
        handle_configuration_form_post(
            post=request.POST,
            actor_id=actor.user_id,
            app=app,
            action=action,
        )
        return None
    if action in CREDENTIAL_ACTIONS:
        return _handle_credential_post(request, actor, app, action=action)
    if action == "run_permission_query_test":
        return run_permission_query_test(
            app=app,
            user_id=request.POST.get("test_user_id", ""),
            plaintext_token=request.POST.get("test_token", ""),
            actor_id=actor.user_id,
        )
    return None


def _handle_credential_post(
    request: HttpRequest,
    actor: ConsoleActor,
    app: App,
    *,
    action: str,
) -> OneTimeSecret | None:
    credential_actor = CredentialActor(actor_id=actor.user_id)
    match action:
        case "create_static_token":
            return create_static_token_for_console(
                app=app,
                name=request.POST.get("credential_name", "").strip(),
                actor=credential_actor,
            )
        case "rotate_static_token":
            return rotate_static_token_for_console(
                app=app,
                credential_id=_post_int(request, "credential_id"),
                actor=credential_actor,
            )
        case "disable_static_token":
            disable_static_token_for_console(
                app=app,
                credential_id=_post_int(request, "credential_id"),
                actor=credential_actor,
            )
            return None
        case "create_oauth_client":
            return create_oauth_client_for_console(
                app=app,
                name=request.POST.get("credential_name", "").strip(),
                actor=credential_actor,
            )
        case _:
            return None


def _visible_app(actor: ConsoleActor, app_key: str) -> App:
    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        raise Http404
    return app


def _action_requires_manage(action: str) -> bool:
    return action != "run_permission_query_test"


def _actor_from_request(request: HttpRequest) -> ConsoleActor | None:
    user = request.user
    if not user.is_authenticated:
        return None
    is_superuser = bool(getattr(user, "is_superuser", False))
    return ConsoleActor(user_id=user.get_username(), is_superuser=is_superuser)


def _login_redirect(request: HttpRequest) -> HttpResponseRedirect:
    return HttpResponseRedirect(f"/admin/login/?next={quote(request.get_full_path())}")


def _post_int(request: HttpRequest, key: str) -> int:
    return int(request.POST.get(key, "0"))

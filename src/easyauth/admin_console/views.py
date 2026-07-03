from __future__ import annotations

from urllib.parse import quote

from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
)
from django.shortcuts import redirect

from easyauth.accounts.dev_login import (
    DevLoginConfigurationError,
    bind_dev_login_session,
    dev_login_is_enabled,
)
from easyauth.accounts.logout_state import browser_is_marked_logged_out, logged_out_redirect
from easyauth.admin_console.identity import actor_from_request
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor, can_view_app
from easyauth.frontend_shell import render_react_shell


def console_home(request: HttpRequest) -> HttpResponse:
    match _page_actor_from_request(request):
        case ConsoleActor():
            return render_react_shell(request, surface="console", title="EasyAuth 控制台")
        case HttpResponse() as response:
            return response
        case None:
            return _login_redirect(request)


def console_operations(request: HttpRequest, _path: str = "") -> HttpResponse:
    match _page_actor_from_request(request):
        case ConsoleActor():
            return render_react_shell(request, surface="console", title="EasyAuth 控制台")
        case HttpResponse() as response:
            return response
        case None:
            return _login_redirect(request)


def app_detail(request: HttpRequest, app_key: str) -> HttpResponse:
    match _page_actor_from_request(request):
        case ConsoleActor() as actor:
            pass
        case HttpResponse() as response:
            return response
        case None:
            return _login_redirect(request)

    app = _visible_app(actor, app_key)

    if request.method == "POST":
        return HttpResponseNotAllowed(
            ["GET"],
            "旧控制台表单入口已关闭, 请使用 /console/api/v1/ 接口。",
            content_type="text/plain; charset=utf-8",
        )

    return render_react_shell(
        request,
        surface="console",
        title=f"{app.name} - EasyAuth 控制台",
        initial_app_key=app.app_key,
    )


def _page_actor_from_request(request: HttpRequest) -> ConsoleActor | HttpResponse | None:
    actor = actor_from_request(request)
    if actor is not None:
        return actor
    if dev_login_is_enabled():
        try:
            _ = bind_dev_login_session(request)
        except DevLoginConfigurationError as error:
            return HttpResponse(str(error), status=400, content_type="text/plain; charset=utf-8")
        return actor_from_request(request)
    return None


def _visible_app(actor: ConsoleActor, app_key: str) -> App:
    app = App.objects.filter(app_key=app_key).first()
    if app is None or not can_view_app(actor, app):
        raise Http404
    return app


def _login_redirect(request: HttpRequest) -> HttpResponseRedirect:
    if browser_is_marked_logged_out(request):
        return logged_out_redirect(request)
    return HttpResponseRedirect(f"/auth/login/?next={quote(request.get_full_path())}")


def _forbidden_redirect() -> HttpResponseRedirect:
    return redirect("/errors/forbidden/")

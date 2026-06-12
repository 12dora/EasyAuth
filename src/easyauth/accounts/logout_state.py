from __future__ import annotations

from urllib.parse import urlencode, urlsplit

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect

from easyauth.frontend_shell import render_public_react_shell

LOGGED_OUT_COOKIE_NAME = "easyauth_logged_out"
LOGGED_OUT_COOKIE_MAX_AGE_SECONDS = 3600
DEFAULT_LOGGED_OUT_NEXT = "/portal/"


def browser_is_marked_logged_out(request: HttpRequest) -> bool:
    return request.COOKIES.get(LOGGED_OUT_COOKIE_NAME) == "1"


def logged_out_redirect(request: HttpRequest) -> HttpResponseRedirect:
    query = urlencode({"next": request.get_full_path()})
    return HttpResponseRedirect(f"/auth/logged-out/?{query}")


def mark_browser_logged_out(response: HttpResponse) -> None:
    response.set_cookie(
        LOGGED_OUT_COOKIE_NAME,
        "1",
        httponly=True,
        max_age=LOGGED_OUT_COOKIE_MAX_AGE_SECONDS,
        samesite="Lax",
    )


def clear_browser_logged_out(response: HttpResponse) -> None:
    response.delete_cookie(LOGGED_OUT_COOKIE_NAME, samesite="Lax")


def logged_out_next_path(request: HttpRequest) -> str:
    next_path = request.GET.get("next", DEFAULT_LOGGED_OUT_NEXT)
    if _is_local_absolute_path(next_path):
        return next_path
    return DEFAULT_LOGGED_OUT_NEXT


def logged_out_response(request: HttpRequest) -> HttpResponse:
    return render_public_react_shell(
        request,
        surface="portal",
        title="已登出 - EasyAuth",
    )


def _is_local_absolute_path(value: str) -> bool:
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "" and parsed.netloc == ""

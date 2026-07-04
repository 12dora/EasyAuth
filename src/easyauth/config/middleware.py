from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from django.http import HttpResponseRedirect

from easyauth.config.error_views import not_found

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.http import HttpRequest, HttpResponse


class SafeNotFoundMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response: Callable[[HttpRequest], HttpResponse]
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self._get_response(request)
        if response.status_code != HTTPStatus.NOT_FOUND:
            return response
        if not _is_html_response(response):
            return response
        return not_found(request)


def _is_html_response(response: HttpResponse) -> bool:
    content_type = response.headers.get("Content-Type", "")
    return content_type == "" or content_type.startswith("text/html")


FORCED_PASSWORD_CHANGE_PATH: Final = "/auth/local/change-password/"  # noqa: S105 - URL 路径, 不是密码值.
# 强制改密期间仍放行的路径前缀: 改密页自身、登出链路和静态资源。
FORCED_PASSWORD_CHANGE_ALLOWED_PREFIXES: Final = (
    "/auth/local/change-password/",
    "/auth/logout/",
    "/auth/logged-out/",
    "/static/",
    "/assets/",
)


class LocalAdminForcedPasswordChangeMiddleware:
    # 本地管理员处于"必须修改密码"状态(首次登录/管理员重置后)时,
    # 除放行前缀外的所有请求(含 /portal/、/console/ 页面与其 API)一律 302 到改密页。
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self._get_response: Callable[[HttpRequest], HttpResponse]
        self._get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if _forced_password_change_allows(request.path):
            return self._get_response(request)
        # 延迟导入避免 config 模块在 Django app 注册完成前触碰 models。
        from easyauth.accounts.local_admin import current_local_admin  # noqa: PLC0415

        account = current_local_admin(request)
        if account is not None and account.must_change_password:
            next_query = quote(request.get_full_path())
            return HttpResponseRedirect(f"{FORCED_PASSWORD_CHANGE_PATH}?next={next_query}")
        return self._get_response(request)


def _forced_password_change_allows(path: str) -> bool:
    return path.startswith(FORCED_PASSWORD_CHANGE_ALLOWED_PREFIXES)

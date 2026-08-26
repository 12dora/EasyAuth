# EasyAuth 统一登录入口(/auth/sign-in/)。
#
# 未登录访问 /portal/ 或 /console/ 先落到这里, 由用户显式点击「使用工作账号登录」
# 再跳 Authentik, 而不是直接 302 出去 —— 用户需要先看到自己进的是 EasyAuth。
# 本地管理员应急通道(/auth/local/)只在页面底部留一个次要入口, 不在此暴露密码表单
# (ADR-003: 本地超管是应急特权通道, 不是面向全员的登录方式)。
#
# 页面是自包含 Django 模板(设计 token 与 accounts/local_admin/login.html、404.html 一致),
# 无前端构建步骤。
from __future__ import annotations

from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from django.shortcuts import render
from django.views.decorators.http import require_GET

from easyauth.accounts.next_path import safe_next_path

if TYPE_CHECKING:
    from django.http import HttpRequest, HttpResponse

SIGN_IN_TEMPLATE: Final = "accounts/sign_in.html"
OIDC_LOGIN_PATH: Final = "/auth/login/"


@require_GET
def sign_in_page(request: HttpRequest) -> HttpResponse:
    next_path = safe_next_path(request.GET.get("next"))
    return render(
        request,
        SIGN_IN_TEMPLATE,
        {"oidc_login_href": oidc_login_href(next_path)},
    )


def oidc_login_href(next_path: str) -> str:
    # quote 的默认 safe="/" 与 admin_console._login_redirect 口径一致:
    # 路径分隔符保持可读, 但 `?`/`&` 必须编码, 否则 next 的查询串会被并进外层 query。
    return f"{OIDC_LOGIN_PATH}?next={quote(next_path, safe='/')}"

from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client, override_settings

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY

pytestmark = pytest.mark.django_db

SIGN_IN_PATH: Final = "/auth/sign-in/"


def test_sign_in_page_renders_without_redirecting_to_authentik() -> None:
    # Given: 匿名浏览器。
    client = Client()

    # When: 打开统一登录入口。
    response = client.get(SIGN_IN_PATH)

    # Then: 直接渲染 EasyAuth 自己的页面, 不 302 去上游。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "登录 EasyAuth" in html
    assert 'href="/auth/login/?next=/portal/">使用工作账号登录' in html


def test_sign_in_page_keeps_local_admin_as_secondary_entry_without_password_form() -> None:
    # Given/When: 匿名打开登录页。
    html = Client().get(SIGN_IN_PATH).content.decode()

    # Then: 只留应急通道链接, 不对全员暴露本地管理员密码表单(ADR-003)。
    assert 'href="/auth/local/"' in html
    assert 'name="password"' not in html
    assert "<form" not in html


def test_sign_in_page_carries_next_through_to_oidc_login() -> None:
    # Given/When: 带站内深链接进入。
    html = Client().get(SIGN_IN_PATH, {"next": "/console/apps/demo"}).content.decode()

    # Then: 「使用工作账号登录」保留原始回跳目标。
    assert 'href="/auth/login/?next=/console/apps/demo"' in html


def test_sign_in_page_encodes_query_in_next() -> None:
    # Given/When: next 自带查询串。
    html = Client().get(SIGN_IN_PATH, {"next": "/console/?tab=roles"}).content.decode()

    # Then: `?` 必须编码, 否则会被并进外层 query 丢失 tab。
    assert 'href="/auth/login/?next=/console/%3Ftab%3Droles"' in html


@pytest.mark.parametrize(
    "hostile_next",
    ["https://evil.example.test/console", "//evil.example.test", "/\\evil.example.test"],
)
def test_sign_in_page_rejects_open_redirect_next(hostile_next: str) -> None:
    # Given/When: 构造开放重定向的 next。
    html = Client().get(SIGN_IN_PATH, {"next": hostile_next}).content.decode()

    # Then: 回落到默认站内路径, 页面不带任何站外目标。
    assert 'href="/auth/login/?next=/portal/">使用工作账号登录' in html
    assert "evil.example.test" not in html


def test_sign_in_page_rejects_post() -> None:
    # Given/When: 登录页是纯展示入口。
    response = Client().post(SIGN_IN_PATH)

    # Then: 不接受表单提交。
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


def test_portal_sends_anonymous_visitor_to_sign_in_page_not_authentik() -> None:
    # Given: 匿名浏览器。
    client = Client()

    # When: 访问门户。
    response = client.get("/portal/")

    # Then: 先落 EasyAuth 登录页(带回跳), 不直接跳上游, 也不产生登录会话。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/sign-in/?next=%2Fportal%2F"
    assert AUTHENTIK_SESSION_KEY not in client.session


def test_console_sends_anonymous_visitor_to_sign_in_page_not_authentik() -> None:
    # Given/When: 匿名访问控制台。
    response = Client().get("/console/")

    # Then: 与门户同口径。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"] == "/auth/sign-in/?next=/console/"


@override_settings(
    EASYAUTH_AUTHENTIK_OIDC_ISSUER="https://authentik.example.test/application/o/easyauth/",
    EASYAUTH_AUTHENTIK_OIDC_AUTHORIZATION_ENDPOINT="",
    EASYAUTH_AUTHENTIK_OIDC_CLIENT_ID="easyauth-portal",
    EASYAUTH_AUTHENTIK_OIDC_REDIRECT_URI="http://testserver/auth/callback/",
    EASYAUTH_AUTHENTIK_OIDC_SCOPES=("openid", "profile", "email"),
)
def test_oidc_login_entry_still_redirects_to_authentik_directly() -> None:
    # Given/When: 点击「使用工作账号登录」后落到的 /auth/login/。
    response = Client().get("/auth/login/?next=/portal/")

    # Then: 该入口维持原语义(直接跳上游), 深链接与下游应用不受落地页影响。
    assert response.status_code == HTTPStatus.FOUND
    assert "/application/o/authorize/" in response.headers["Location"]

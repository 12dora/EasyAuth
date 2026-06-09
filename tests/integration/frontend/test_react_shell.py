from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, AppMembership

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "react-shell-login"


def test_console_home_serves_react_shell_for_authenticated_admin() -> None:
    # Given: 系统管理员已登录控制台。
    client = _logged_in_django_user("react-console-admin", is_superuser=True)

    # When: 打开控制台首页。
    response = client.get("/console/")

    # Then: Django 返回 React 挂载壳, 由前端消费同源私有 API。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'data-easyauth-react-shell="console"' in html
    assert 'data-brand-logo-url="/static/easyauth/frontend/assets/brand/jiefa_logo.webp"' in html
    assert 'id="easyauth-root"' in html
    assert 'name="csrfmiddlewaretoken"' in html


def test_console_app_detail_serves_react_shell_without_leaking_unowned_app() -> None:
    # Given: 应用负责人只拥有一个 App。
    client = _logged_in_django_user("react-console-owner")
    owned_app = App.objects.create(app_key="react-owned-crm", name="React CRM")
    unowned_app = App.objects.create(app_key="react-unowned-erp", name="React ERP")
    _ = AppMembership.objects.create(app=owned_app, user_id="react-console-owner", role="owner")

    # When: 打开已拥有 App 和未拥有 App 的 React 页面。
    owned_response = client.get(f"/console/apps/{owned_app.app_key}/")
    unowned_response = client.get(f"/console/apps/{unowned_app.app_key}/")

    # Then: 已授权页面返回 React 壳, 未授权 App 仍不暴露。
    html = owned_response.content.decode()
    assert owned_response.status_code == HTTPStatus.OK
    assert 'data-easyauth-react-shell="console"' in html
    assert f'data-initial-app-key="{owned_app.app_key}"' in html
    assert unowned_response.status_code == HTTPStatus.NOT_FOUND


def test_portal_serves_react_shell_for_active_session_user() -> None:
    # Given: 员工门户 session 绑定 active UserMirror。
    client = Client()
    user = UserMirror.objects.create(
        authentik_user_id="react-portal-user",
        name="门户用户",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()

    # When: 打开员工门户。
    response = client.get("/portal/")

    # Then: Django 返回员工门户 React 壳。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'data-easyauth-react-shell="portal"' in html
    assert 'id="easyauth-root"' in html
    assert "员工门户" in html


@pytest.mark.parametrize(
    "path",
    ["/portal/request", "/portal/requests", "/portal/expiring"],
)
def test_portal_client_routes_serve_react_shell_for_active_session_user(path: str) -> None:
    # Given: 员工门户 session 绑定 active UserMirror。
    client = Client()
    user = UserMirror.objects.create(
        authentik_user_id=f"react-portal-route-user-{path.rsplit('/', maxsplit=1)[-1]}",
        name="门户路由用户",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()

    # When: 直接打开 React client route。
    response = client.get(path)

    # Then: Django 返回同一个员工门户 React 壳, 供前端 router 接管。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'data-easyauth-react-shell="portal"' in html
    assert 'id="easyauth-root"' in html
    assert user.authentik_user_id in html


def test_portal_client_route_redirects_to_login_without_session() -> None:
    # Given: 未登录 client。
    client = Client()

    # When: 直接打开 React client route。
    response = client.get("/portal/request")

    # Then: 非 API 子路由仍保持门户登录边界。
    assert response.status_code == HTTPStatus.FOUND
    assert response.headers["Location"].startswith("/auth/login/")


def test_portal_api_route_is_not_captured_by_react_catch_all() -> None:
    # Given: 未登录 client。
    client = Client()

    # When: 访问门户 API。
    response = client.get("/portal/api/v1/me/grants")

    # Then: API 仍返回 JSON session 错误, 不被 React catch-all 吞掉。
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["Content-Type"].startswith("application/json")


def _logged_in_django_user(username: str, *, is_superuser: bool = False) -> Client:
    _ = User.objects.create_user(
        username=username,
        password=LOGIN_VALUE,
        is_superuser=is_superuser,
        is_staff=is_superuser,
    )
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client

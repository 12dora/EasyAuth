from __future__ import annotations

from http import HTTPStatus

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, AppMembership

pytestmark = pytest.mark.django_db


def test_console_home_serves_react_shell_for_authenticated_admin() -> None:
    # Given: 系统管理员已登录控制台。
    client = _logged_in_console_user(
        "react-console-admin",
        is_superuser=True,
        name="控制台用户",
        avatar_url="https://authentik.example.test/media/avatars/admin.png",
    )

    # When: 打开控制台首页。
    response = client.get("/console/")

    # Then: Django 返回 React 挂载壳, 由前端消费同源私有 API。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Cache-Control"] == "no-store"
    assert 'data-easyauth-react-shell="console"' in html
    assert 'data-brand-logo-url="/static/easyauth/frontend/assets/brand/jiefa_logo.webp"' in html
    assert 'data-current-user-id="react-console-admin"' in html
    assert 'data-current-user-display-name="控制台用户"' in html
    assert 'data-current-user-role="EasyAuth Admins"' in html
    assert (
        'data-current-user-avatar-url="https://authentik.example.test/media/avatars/admin.png"'
        in html
    )
    assert 'data-logout-url="/auth/logout/"' in html
    assert 'id="easyauth-root"' in html
    assert 'name="csrfmiddlewaretoken"' in html


def test_console_app_detail_serves_react_shell_without_leaking_unowned_app() -> None:
    # Given: 应用负责人只拥有一个 App。
    client = _logged_in_console_user("react-console-owner")
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
        avatar_url="https://authentik.example.test/media/avatars/portal.png",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session[AUTHENTIK_GROUPS_SESSION_KEY] = ["研发中心"]
    session.save()

    # When: 打开员工门户。
    response = client.get("/portal/")

    # Then: Django 返回员工门户 React 壳。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Cache-Control"] == "no-store"
    assert 'data-easyauth-react-shell="portal"' in html
    assert 'data-current-user-id="react-portal-user"' in html
    assert 'data-current-user-display-name="门户用户"' in html
    assert 'data-current-user-role="研发中心"' in html
    assert (
        'data-current-user-avatar-url="https://authentik.example.test/media/avatars/portal.png"'
        in html
    )
    assert 'data-logout-url="/auth/logout/"' in html
    assert 'id="easyauth-root"' in html
    assert "员工门户" in html


def test_portal_shell_uses_placeholder_display_name_when_profile_name_is_missing() -> None:
    # Given: authentik subject 很长, 但还没有同步到友好的 name/email。
    client = Client()
    long_subject = "dingmockcorp000000000000000000000000:100000000000000001"
    user = UserMirror.objects.create(
        authentik_user_id=long_subject,
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()

    # When: 打开员工门户。
    response = client.get("/portal/")

    # Then: 展示名不回退到超长 subject。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert 'data-current-user-id="dingmockcorp000000000000000000000000:100000000000000001"' in html
    assert 'data-current-user-display-name="当前用户"' in html


def test_logged_out_page_serves_portal_react_shell_without_current_user() -> None:
    # Given: 浏览器被登出重定向到本地登出页。
    client = Client()

    # When: 打开登出页。
    response = client.get("/auth/logged-out/?next=%2Fportal%2F")

    # Then: Django 返回共用 React 壳, 且不会注入当前用户姓名、角色或头像。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Cache-Control"] == "no-store"
    assert 'data-easyauth-react-shell="portal"' in html
    assert 'id="easyauth-root"' in html
    assert "已登出 - EasyAuth" in html
    assert "data-current-user-id" not in html
    assert "data-current-user-display-name" not in html
    assert "data-current-user-role" not in html
    assert "data-current-user-avatar-url" not in html


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
    assert 'data-current-user-display-name="门户路由用户"' in html


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


def _logged_in_console_user(
    username: str,
    *,
    avatar_url: str = "",
    is_superuser: bool = False,
    name: str = "",
) -> Client:
    user, _created = UserMirror.objects.get_or_create(
        authentik_user_id=username,
        defaults={"avatar_url": avatar_url, "name": name, "status": USER_STATUS_ACTIVE},
    )
    if user.name != name or user.avatar_url != avatar_url:
        user.name = name
        user.avatar_url = avatar_url
        user.save(update_fields=["name", "avatar_url", "updated_at"])
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    if is_superuser:
        session[AUTHENTIK_GROUPS_SESSION_KEY] = ["EasyAuth Admins"]
    session.save()
    return client

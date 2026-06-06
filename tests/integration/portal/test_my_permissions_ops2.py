from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, Permission, Role, RolePermission
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantPermission,
    AccessGrantRole,
)

pytestmark = pytest.mark.django_db

PORTAL_URL: Final = "/portal/"
EXPIRING_SOON_DAYS: Final = 14


def test_ops2_portal_lists_my_current_permissions_for_active_grants() -> None:
    # Given: 当前登录员工有一条长期有效授权, 以及不应展示的他人授权和历史授权。
    client, user = _logged_in_client("ops2-current-user")
    crm_app, crm_grant = _create_grant(
        user=user,
        app_key="ops2-current-crm",
        app_name="CRM",
        version=3,
    )
    crm_role = Role.objects.create(app=crm_app, key="auditor", name="CRM 审计员")
    read_permission = Permission.objects.create(
        app=crm_app,
        key="invoice.read",
        name="查看发票",
    )
    approve_permission = Permission.objects.create(
        app=crm_app,
        key="invoice.approve",
        name="审批发票",
    )
    _ = RolePermission.objects.create(role=crm_role, permission=read_permission)
    _ = AccessGrantRole.objects.create(grant=crm_grant, role=crm_role)
    _ = AccessGrantPermission.objects.create(grant=crm_grant, permission=approve_permission)
    _create_other_user_grant(app_name="其他用户应用")
    _ = _create_revoked_grant(
        user=user,
        app_key="ops2-revoked-app",
        app_name="已撤销应用",
    )

    # When: 员工打开门户。
    response = client.get(PORTAL_URL)

    # Then: “我的权限”只展示当前登录员工的 active current grant。
    section = _section_html(response.content.decode(), "current-permissions")
    assert response.status_code == HTTPStatus.OK
    assert "我的权限" in section
    assert "CRM" in section
    assert "CRM 审计员" in section
    assert "invoice.approve" in section
    assert "invoice.read" in section
    assert "v3" in section
    assert "长期" in section
    assert "其他用户应用" not in section
    assert "已撤销应用" not in section


def test_ops2_portal_lists_only_expiring_grants_within_fourteen_days() -> None:
    # Given: 当前员工有 14 天内到期、14 天后到期和长期授权。
    client, user = _logged_in_client("ops2-expiring-user")
    now = timezone.now()
    _ = _create_timed_grant(
        user=user,
        app_key="ops2-near-expiring",
        app_name="即将过期 CRM",
        expires_at=now + timedelta(days=EXPIRING_SOON_DAYS),
    )
    _ = _create_timed_grant(
        user=user,
        app_key="ops2-far-expiring",
        app_name="暂不提醒应用",
        expires_at=now + timedelta(days=EXPIRING_SOON_DAYS + 1),
    )
    _ = _create_grant(user=user, app_key="ops2-permanent", app_name="长期授权应用")

    # When: 员工打开门户。
    response = client.get(PORTAL_URL)

    # Then: “即将过期”只展示未来 14 天内的限时授权。
    section = _section_html(response.content.decode(), "expiring-grants")
    assert response.status_code == HTTPStatus.OK
    assert "即将过期" in section
    assert "即将过期 CRM" in section
    assert "限时" in section
    assert "暂不提醒应用" not in section
    assert "长期授权应用" not in section


def test_ops2_portal_shows_empty_states_when_user_has_no_current_grants() -> None:
    # Given: 当前登录员工没有任何当前有效授权。
    client, _user = _logged_in_client("ops2-empty-user")

    # When: 员工打开门户。
    response = client.get(PORTAL_URL)

    # Then: 门户用中文空状态区分当前授权和即将过期授权。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "暂无当前授权" in html
    assert "暂无即将过期授权" in html


def test_ops2_portal_explains_request_status_before_grant_is_effective() -> None:
    # Given: 当前登录员工打开申请状态面板。
    client, _user = _logged_in_client("ops2-status-guide-user")

    # When: 员工打开门户。
    response = client.get(PORTAL_URL)

    # Then: 状态说明明确区分审批通过和授权生效。
    section = _section_html(response.content.decode(), "request-status")
    assert response.status_code == HTTPStatus.OK
    assert "审批已通过, 等待授权落库" in section
    assert "授权已落库, 权限已生效" in section
    assert "授权落库失败" in section


def _logged_in_client(authentik_user_id: str) -> tuple[Client, UserMirror]:
    client = Client()
    user = UserMirror.objects.create(
        authentik_user_id=authentik_user_id,
        name="门户用户",
        status=USER_STATUS_ACTIVE,
    )
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client, user


def _create_grant(
    *,
    user: UserMirror,
    app_key: str,
    app_name: str,
    version: int = 1,
) -> tuple[App, AccessGrant]:
    app = App.objects.create(app_key=app_key, name=app_name)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        version=version,
    )
    return app, grant


def _create_timed_grant(
    *,
    user: UserMirror,
    app_key: str,
    app_name: str,
    expires_at: datetime,
) -> tuple[App, AccessGrant]:
    app = App.objects.create(app_key=app_key, name=app_name)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_TIMED,
        grant_expires_at=expires_at,
    )
    return app, grant


def _create_revoked_grant(
    *,
    user: UserMirror,
    app_key: str,
    app_name: str,
) -> tuple[App, AccessGrant]:
    app = App.objects.create(app_key=app_key, name=app_name)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
    )
    return app, grant


def _create_other_user_grant(*, app_name: str) -> None:
    other_user = UserMirror.objects.create(authentik_user_id="ops2-other-user")
    _ = _create_grant(user=other_user, app_key="ops2-other-app", app_name=app_name)


def _section_html(html: str, section_name: str) -> str:
    marker = f'data-ops2-section="{section_name}"'
    start_index = html.find(marker)
    if start_index == -1:
        return ""
    end_index = html.find("</section>", start_index)
    if end_index == -1:
        return html[start_index:]
    return html[start_index:end_index]

from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Final

import pytest
from django.utils import timezone

from easyauth.access_requests.models import (
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    AccessRequest,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from tests.integration.portal.helpers import logged_in_client

pytestmark = pytest.mark.django_db

GRANTS_API_URL: Final = "/portal/api/v1/me/grants"
EXPIRING_API_URL: Final = "/portal/api/v1/me/grants/expiring"
REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"
EXPIRING_SOON_DAYS: Final = 14


def test_ops2_portal_lists_my_current_permissions_for_active_grants() -> None:
    # Given: 当前登录员工有一条长期有效授权, 以及不应展示的他人授权和历史授权。
    client, user = logged_in_client("ops2-current-user")
    crm_app, crm_grant = _create_grant(
        user=user,
        app_key="ops2-current-crm",
        app_name="CRM",
        version=3,
    )
    _ = AppScope.objects.create(app=crm_app, key="SELF", name="本人")
    crm_group = AuthorizationGroup.objects.create(
        app=crm_app,
        key="auditor",
        kind="role",
        name="CRM 审计员",
    )
    read_permission = Permission.objects.create(
        app=crm_app,
        key="invoice.read",
        name="查看发票",
        supported_scopes=["SELF"],
    )
    approve_permission = Permission.objects.create(
        app=crm_app,
        key="invoice.approve",
        name="审批发票",
        supported_scopes=["SELF"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=crm_group,
        permission=read_permission,
        scope_key="SELF",
    )
    _ = AccessGrantGroup.objects.create(grant=crm_grant, authorization_group=crm_group)
    _ = AccessGrantPermission.objects.create(
        grant=crm_grant,
        permission=approve_permission,
        scope_key="SELF",
    )
    _create_other_user_grant(app_name="其他用户应用")
    _ = _create_revoked_grant(
        user=user,
        app_key="ops2-revoked-app",
        app_name="已撤销应用",
    )

    # When: 员工读取当前授权 API。
    response = client.get(GRANTS_API_URL)

    # Then: API 只返回当前登录员工的 active current grant。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "CRM" in body
    assert "CRM 审计员" in body
    assert "invoice.approve" in body
    assert "invoice.read" in body
    assert '"grant_version": 3' in body
    assert '"catalog_version": 1' in body
    assert '"snapshot_version": "3.1"' in body
    assert GRANT_TYPE_PERMANENT in body
    assert "其他用户应用" not in body
    assert "已撤销应用" not in body


def test_ops2_portal_lists_only_expiring_grants_within_fourteen_days() -> None:
    # Given: 当前员工有 14 天内到期、14 天后到期和长期授权。
    client, user = logged_in_client("ops2-expiring-user")
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

    # When: 员工读取即将过期授权 API。
    response = client.get(EXPIRING_API_URL, {"days": str(EXPIRING_SOON_DAYS)})

    # Then: API 只返回未来 14 天内的限时授权。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "即将过期 CRM" in body
    assert GRANT_TYPE_TIMED in body
    assert "暂不提醒应用" not in body
    assert "长期授权应用" not in body


def test_ops2_portal_shows_empty_states_when_user_has_no_current_grants() -> None:
    # Given: 当前登录员工没有任何当前有效授权。
    client, _user = logged_in_client("ops2-empty-user")

    # When: 员工读取当前授权和即将过期授权 API。
    grants = client.get(GRANTS_API_URL)
    expiring = client.get(EXPIRING_API_URL)

    # Then: API 返回空列表, 空状态文案由 React shell 呈现。
    assert grants.status_code == HTTPStatus.OK
    assert expiring.status_code == HTTPStatus.OK
    assert grants.json()["data"] == []
    assert expiring.json()["data"] == []


def test_ops2_portal_explains_request_status_before_grant_is_effective() -> None:
    # Given: 当前登录员工已有审批通过、授权生效和授权失败申请。
    client, user = logged_in_client("ops2-status-guide-user")
    app = App.objects.create(app_key="ops2-status-guide-app", name="CRM")
    _ = AccessRequest.objects.create(user=user, app=app, status=REQUEST_STATUS_APPROVED)
    _ = AccessRequest.objects.create(user=user, app=app, status=REQUEST_STATUS_GRANT_APPLIED)
    _ = AccessRequest.objects.create(user=user, app=app, status=REQUEST_STATUS_GRANT_FAILED)

    # When: 员工读取申请状态 API。
    response = client.get(REQUESTS_API_URL)

    # Then: API 状态文案明确区分审批通过和授权生效。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "审批已通过, 等待授权落库" in body
    assert "授权已落库, 权限已生效" in body
    assert "授权落库失败" in body


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

from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from typing import Final

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    GRANT_TYPE_TIMED,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
    AccessRequestRole,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App, ApprovalRule, Role
from easyauth.grants.models import AccessGrant
from easyauth.portal.views import request_rows_for_user

pytestmark = pytest.mark.django_db

PORTAL_URL: Final = "/portal/"
EXPECTED_REQUEST_ROW_COUNT: Final = 3
EXPECTED_REQUEST_ROW_QUERIES: Final = 2


def test_s14_portal_renders_compact_request_form_for_requestable_roles() -> None:
    # Given: 员工已登录, 且只有一个角色满足可申请和审批规则要求。
    client, _user = _logged_in_client("s14-portal-form-user")
    app = App.objects.create(app_key="s14-portal-crm", name="CRM")
    requestable_role = Role.objects.create(
        app=app,
        key="admin",
        name="CRM 管理员",
        requestable=True,
    )
    _ = Role.objects.create(
        app=app,
        key="internal",
        name="内部维护",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        role=requestable_role,
        approver_userids=["manager-001"],
    )

    # When: 员工打开门户。
    response = client.get(PORTAL_URL)

    # Then: 页面展示真实申请表单, 且不展示无审批规则角色。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert response.headers["Content-Type"].startswith("text/html")
    assert "EasyAuth 员工门户" in html
    assert "CRM 管理员" in html
    assert "内部维护" not in html
    assert 'name="grant_type"' in html
    assert 'name="grant_expires_at"' in html
    assert 'name="reason"' in html
    assert 'data-s14-surface="access-request"' in html


def test_s14_portal_submit_creates_request_through_service_without_creating_grant() -> None:
    # Given: 员工选择一个有效角色和永久授权生命周期。
    client, user = _logged_in_client("s14-portal-submit-user")
    app = App.objects.create(app_key="s14-portal-submit-app", name="CRM")
    role = Role.objects.create(app=app, key="auditor", name="CRM 审计员", requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])

    # When: 员工提交门户表单。
    response = client.post(
        PORTAL_URL,
        {
            "app_id": str(app.id),
            "role_id": str(role.id),
            "grant_type": GRANT_TYPE_PERMANENT,
            "grant_expires_at": "",
            "reason": "需要查看客户变更记录",
        },
        follow=True,
    )

    # Then: 门户展示 submitted 状态, 数据只经过申请服务落库, 不直接授权。
    html = response.content.decode()
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert response.status_code == HTTPStatus.OK
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert AccessRequestRole.objects.get(access_request=access_request).role == role
    assert access_request.reason == "需要查看客户变更记录"
    assert AccessGrant.objects.count() == 0
    assert "已提交" in html
    assert "CRM 审计员" in html


def test_s14_portal_rejects_role_without_approval_rule() -> None:
    # Given: 员工提交一个没有审批规则的角色。
    client, _user = _logged_in_client("s14-portal-invalid-user")
    app = App.objects.create(app_key="s14-portal-invalid-app", name="CRM")
    role = Role.objects.create(app=app, key="no-rule", name="无规则角色", requestable=True)

    # When: 员工提交门户表单。
    response = client.post(
        PORTAL_URL,
        {
            "app_id": str(app.id),
            "role_id": str(role.id),
            "grant_type": GRANT_TYPE_PERMANENT,
            "grant_expires_at": "",
            "reason": "测试非法配置",
        },
    )

    # Then: 门户拒绝提交, 且没有绕过服务创建申请或授权。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "该角色当前不可申请" in html
    assert AccessRequest.objects.count() == 0
    assert AccessGrant.objects.count() == 0


def test_s14_portal_status_list_distinguishes_request_statuses() -> None:
    # Given: 员工已经有各类申请状态。
    client, user = _logged_in_client("s14-portal-status-user")
    app = App.objects.create(app_key="s14-portal-status-app", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="CRM 管理员", requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    statuses = (
        REQUEST_STATUS_SUBMITTED,
        REQUEST_STATUS_APPROVED,
        REQUEST_STATUS_GRANT_APPLIED,
        REQUEST_STATUS_REJECTED,
        REQUEST_STATUS_GRANT_FAILED,
    )
    for status in statuses:
        access_request = AccessRequest.objects.create(
            user=user,
            app=app,
            status=status,
            applied_at=timezone.now() if status == REQUEST_STATUS_GRANT_APPLIED else None,
        )
        _ = AccessRequestRole.objects.create(access_request=access_request, role=role)

    # When: 员工打开门户。
    response = client.get(PORTAL_URL)

    # Then: 状态列表用业务文案区分所有状态。
    html = response.content.decode()
    assert "已提交" in html
    assert "已批准" in html
    assert "已授权" in html
    assert "已拒绝" in html
    assert "授权失败" in html


def test_s14_portal_request_rows_load_role_names_in_bulk() -> None:
    # Given: 员工有多条申请状态行。
    _client, user = _logged_in_client("s14-portal-query-user")
    app = App.objects.create(app_key="s14-portal-query-app", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="CRM 管理员", requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    for index in range(3):
        access_request = AccessRequest.objects.create(
            user=user,
            app=app,
            reason=f"批量查询 {index}",
        )
        _ = AccessRequestRole.objects.create(access_request=access_request, role=role)

    # When: 门户构建状态表行。
    with CaptureQueriesContext(connection) as captured_queries:
        rows = request_rows_for_user(user)

    # Then: 多行角色名通过固定查询数批量加载。
    assert len(rows) == EXPECTED_REQUEST_ROW_COUNT
    assert {row.role_names for row in rows} == {"CRM 管理员"}
    assert len(captured_queries) == EXPECTED_REQUEST_ROW_QUERIES


def test_s14_portal_timed_request_requires_expiration() -> None:
    # Given: 员工选择限时授权但没有填写到期时间。
    client, _user = _logged_in_client("s14-portal-timed-user")
    app = App.objects.create(app_key="s14-portal-timed-app", name="CRM")
    role = Role.objects.create(app=app, key="operator", name="CRM 操作员", requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])

    # When: 员工提交无到期时间的限时申请。
    response = client.post(
        PORTAL_URL,
        {
            "app_id": str(app.id),
            "role_id": str(role.id),
            "grant_type": GRANT_TYPE_TIMED,
            "grant_expires_at": "",
            "reason": "临时处理客户资料",
        },
    )

    # Then: 门户提示生命周期校验错误。
    html = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "请选择限时授权的到期时间" in html
    assert AccessRequest.objects.count() == 0


def test_s14_portal_timed_request_creates_request_with_expiration() -> None:
    # Given: 员工选择限时授权并填写到期时间。
    client, user = _logged_in_client("s14-portal-timed-submit-user")
    app = App.objects.create(app_key="s14-portal-timed-submit-app", name="CRM")
    role = Role.objects.create(app=app, key="operator", name="CRM 操作员", requestable=True)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    expires_at = timezone.localtime(timezone.now() + timedelta(days=7))

    # When: 员工提交限时申请。
    response = client.post(
        PORTAL_URL,
        {
            "app_id": str(app.id),
            "role_id": str(role.id),
            "grant_type": GRANT_TYPE_TIMED,
            "grant_expires_at": expires_at.strftime("%Y-%m-%dT%H:%M"),
            "reason": "临时处理客户资料",
        },
        follow=True,
    )

    # Then: 申请保留限时生命周期和到期时间。
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert response.status_code == HTTPStatus.OK
    assert access_request.grant_type == GRANT_TYPE_TIMED
    assert access_request.grant_expires_at is not None


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

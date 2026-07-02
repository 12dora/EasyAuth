from __future__ import annotations

from datetime import timedelta
from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.db import connection
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
    AccessRequestGroup,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, ApprovalRule, AuthorizationGroup
from easyauth.grants.models import AccessGrant
from easyauth.portal.views import request_rows_for_user
from tests.integration.portal.helpers import logged_in_client

pytestmark = pytest.mark.django_db

REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"
EXPECTED_REQUEST_ROW_COUNT: Final = 3
EXPECTED_REQUEST_ROW_QUERIES: Final = 2


def test_s14_portal_api_accepts_only_requestable_authorization_groups() -> None:
    # Given: 员工已登录, 且只有一个授权组满足可申请要求。
    client, user = logged_in_client("s14-portal-form-user")
    app = App.objects.create(app_key="s14-portal-crm", name="CRM")
    requestable_group = _requestable_group_with_rule(
        app=app,
        key="admin",
        name="CRM 管理员",
    )
    _ = AuthorizationGroup.objects.create(
        app=app,
        key="internal",
        kind="role",
        name="内部维护",
        requestable=False,
    )

    # When: 员工分别通过门户 API 申请可申请授权组和不可申请授权组。
    accepted = client.post(
        REQUESTS_API_URL,
        data=_access_request_payload(
            app_key=app.app_key,
            authorization_group_keys=[requestable_group.key],
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="需要管理员权限",
        ),
        content_type="application/json",
    )
    rejected = client.post(
        REQUESTS_API_URL,
        data=_access_request_payload(
            app_key=app.app_key,
            authorization_group_keys=["internal"],
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="尝试申请内部维护",
        ),
        content_type="application/json",
    )

    # Then: API 只创建合规授权组申请。
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert accepted.status_code == HTTPStatus.CREATED
    assert rejected.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert (
        AccessRequestGroup.objects.get(access_request=access_request).authorization_group
        == requestable_group
    )
    assert AccessRequest.objects.count() == 1
    assert AccessGrant.objects.count() == 0


def test_s14_portal_submit_creates_request_through_service_without_creating_grant() -> None:
    # Given: 员工选择一个有效授权组和永久授权生命周期。
    client, user = logged_in_client("s14-portal-submit-user")
    app = App.objects.create(app_key="s14-portal-submit-app", name="CRM")
    group = _requestable_group_with_rule(
        app=app,
        key="auditor",
        name="CRM 审计员",
    )

    # When: 员工提交门户申请 API。
    response = client.post(
        REQUESTS_API_URL,
        data=_access_request_payload(
            app_key=app.app_key,
            authorization_group_keys=[group.key],
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="需要查看客户变更记录",
        ),
        content_type="application/json",
    )

    # Then: 门户 API 返回 submitted 状态, 数据只经过申请服务落库, 不直接授权。
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert response.status_code == HTTPStatus.CREATED
    assert access_request.status == REQUEST_STATUS_SUBMITTED
    assert (
        AccessRequestGroup.objects.get(access_request=access_request).authorization_group
        == group
    )
    assert access_request.reason == "需要查看客户变更记录"
    assert AccessGrant.objects.count() == 0
    assert "等待审批" in response.content.decode()
    assert "CRM 审计员" in response.content.decode()


def test_s14_portal_rejects_non_requestable_authorization_group() -> None:
    # Given: 员工提交一个不可申请授权组。
    client, _user = logged_in_client("s14-portal-invalid-user")
    app = App.objects.create(app_key="s14-portal-invalid-app", name="CRM")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="internal",
        kind="role",
        name="内部授权",
        requestable=False,
    )

    # When: 员工提交门户申请 API。
    response = client.post(
        REQUESTS_API_URL,
        data=_access_request_payload(
            app_key=app.app_key,
            authorization_group_keys=[group.key],
            grant_type=GRANT_TYPE_PERMANENT,
            grant_expires_at=None,
            reason="测试非法配置",
        ),
        content_type="application/json",
    )

    # Then: 门户 API 拒绝提交, 且没有绕过服务创建申请或授权。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "Authorization group must be requestable" in response.content.decode()
    assert AccessRequest.objects.count() == 0
    assert AccessGrant.objects.count() == 0


def test_s14_portal_status_list_distinguishes_request_statuses() -> None:
    # Given: 员工已经有各类申请状态。
    client, user = logged_in_client("s14-portal-status-user")
    app = App.objects.create(app_key="s14-portal-status-app", name="CRM")
    group = AuthorizationGroup.objects.create(app=app, key="admin", kind="role", name="CRM 管理员")
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
        _ = AccessRequestGroup.objects.create(
            access_request=access_request,
            authorization_group=group,
        )

    # When: 员工读取门户申请列表 API。
    response = client.get(REQUESTS_API_URL)

    # Then: API 状态列表用业务文案区分所有状态。
    body = response.content.decode()
    assert "等待审批" in body
    assert "审批已通过, 等待授权落库" in body
    assert "授权已落库, 权限已生效" in body
    assert "已拒绝" in body
    assert "授权落库失败" in body


def test_s14_portal_request_rows_load_role_names_in_bulk() -> None:
    # Given: 员工有多条申请状态行。
    _client, user = logged_in_client("s14-portal-query-user")
    app = App.objects.create(app_key="s14-portal-query-app", name="CRM")
    group = AuthorizationGroup.objects.create(app=app, key="admin", kind="role", name="CRM 管理员")
    for index in range(3):
        access_request = AccessRequest.objects.create(
            user=user,
            app=app,
            reason=f"批量查询 {index}",
        )
        _ = AccessRequestGroup.objects.create(
            access_request=access_request,
            authorization_group=group,
        )

    # When: 门户构建状态表行。
    with CaptureQueriesContext(connection) as captured_queries:
        rows = request_rows_for_user(user)

    # Then: 多行角色名通过固定查询数批量加载。
    assert len(rows) == EXPECTED_REQUEST_ROW_COUNT
    assert {row.role_names for row in rows} == {"CRM 管理员"}
    assert len(captured_queries) == EXPECTED_REQUEST_ROW_QUERIES


def test_s14_portal_timed_request_requires_expiration() -> None:
    # Given: 员工选择限时授权但没有填写到期时间。
    client, _user = logged_in_client("s14-portal-timed-user")
    app = App.objects.create(app_key="s14-portal-timed-app", name="CRM")
    group = _requestable_group_with_rule(
        app=app,
        key="operator",
        name="CRM 操作员",
    )

    # When: 员工通过门户 API 提交无到期时间的限时申请。
    response = client.post(
        REQUESTS_API_URL,
        data=_access_request_payload(
            app_key=app.app_key,
            authorization_group_keys=[group.key],
            grant_type=GRANT_TYPE_TIMED,
            grant_expires_at=None,
            reason="临时处理客户资料",
        ),
        content_type="application/json",
    )

    # Then: API 提示生命周期校验错误。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "Timed requests must include an expiration" in response.content.decode()
    assert AccessRequest.objects.count() == 0


def test_s14_portal_timed_request_creates_request_with_expiration() -> None:
    # Given: 员工选择限时授权并填写到期时间。
    client, user = logged_in_client("s14-portal-timed-submit-user")
    app = App.objects.create(app_key="s14-portal-timed-submit-app", name="CRM")
    group = _requestable_group_with_rule(
        app=app,
        key="operator",
        name="CRM 操作员",
    )
    expires_at = timezone.localtime(timezone.now() + timedelta(days=7))

    # When: 员工通过门户 API 提交限时申请。
    response = client.post(
        REQUESTS_API_URL,
        data=_access_request_payload(
            app_key=app.app_key,
            authorization_group_keys=[group.key],
            grant_type=GRANT_TYPE_TIMED,
            grant_expires_at=expires_at.isoformat(),
            reason="临时处理客户资料",
        ),
        content_type="application/json",
    )

    # Then: 申请保留限时生命周期和到期时间。
    access_request = AccessRequest.objects.get(user=user, app=app)
    assert response.status_code == HTTPStatus.CREATED
    assert access_request.grant_type == GRANT_TYPE_TIMED
    assert access_request.grant_expires_at is not None


def _access_request_payload(
    *,
    app_key: str,
    authorization_group_keys: list[str],
    grant_type: str,
    grant_expires_at: str | None,
    reason: str,
) -> str:
    approver, _created = UserMirror.objects.get_or_create(
        authentik_user_id="s14-portal-default-approver",
    )
    return dumps(
        {
            "app_key": app_key,
            "authorization_group_keys": authorization_group_keys,
            "direct_grants": [],
            "approver_user_ids": [approver.authentik_user_id],
            "grant_type": grant_type,
            "grant_expires_at": grant_expires_at,
            "reason": reason,
        },
    )


def _requestable_group_with_rule(*, app: App, key: str, name: str) -> AuthorizationGroup:
    group = AuthorizationGroup.objects.create(
        app=app,
        key=key,
        kind="role",
        name=name,
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )
    return group

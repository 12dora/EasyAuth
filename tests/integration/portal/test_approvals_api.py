from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from pydantic import TypeAdapter

from easyauth.access_requests.application_grants import GrantApplyFailureError
from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    AccessRequest,
    AccessRequestApprover,
    AccessRequestGroup,
)
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import JsonValue
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import AccessGrant
from tests.integration.portal.helpers import logged_in_client

pytestmark = pytest.mark.django_db

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
GRANT_FAILURE_MESSAGE: Final = "外部授权写入失败"


def test_approver_sees_pending_approvals_and_approves() -> None:
    # Given: 审批人登录 portal, 存在一条待其审批的申请。
    client, approver = logged_in_client("portal-approver")
    access_request = _submitted_request(
        "portal-applicant",
        "portal-approve-app",
        approver_id=approver.authentik_user_id,
    )

    # When: 查看待办并同意。
    pending = client.get("/portal/api/v1/me/approvals")
    detail = client.get(f"/portal/api/v1/me/approvals/{access_request.id}")
    approved = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/approve",
        data=dumps({"comment": "没问题"}),
        content_type="application/json",
    )

    # Then: 待办可见、详情含申请人信息、同意后授权自动生效。
    pending_body = _json_object(pending.content)
    detail_body = _json_object(detail.content)
    approved_body = _json_object(approved.content)
    assert pending.status_code == HTTPStatus.OK
    pending_data = pending_body["data"]
    assert isinstance(pending_data, list)
    assert len(pending_data) == 1
    first = pending_data[0]
    assert isinstance(first, dict)
    assert first["id"] == access_request.id
    authorization_groups = first["authorization_groups"]
    assert isinstance(authorization_groups, list)
    group = authorization_groups[0]
    assert isinstance(group, dict)
    assert group["grants"] == [
        {
            "permission": "reader.view",
            "permission_name": "Reader View",
            "scope": "GLOBAL",
        },
    ]
    applicant = _json_dict(detail_body, "approval")["applicant"]
    assert isinstance(applicant, dict)
    assert applicant["user_id"] == "portal-applicant"
    approval = _json_dict(approved_body, "approval")
    assert approval["status"] == "grant_applied"
    assert AccessGrant.objects.filter(is_current=True).count() == 1


def test_approve_application_failure_returns_committed_decision_and_latest_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 审批人同意时, 授权事实写入失败。
    client, approver = logged_in_client("portal-failed-approver")
    access_request = _submitted_request(
        "portal-failed-applicant",
        "portal-failed-app",
        approver_id=approver.authentik_user_id,
    )

    def fail_grant_application(*_args: object, **_kwargs: object) -> None:
        raise GrantApplyFailureError(GRANT_FAILURE_MESSAGE)

    monkeypatch.setattr(
        "easyauth.access_requests.application.apply_grant_fact",
        fail_grant_application,
    )

    # When
    response = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/approve",
        data=dumps({"comment": "同意"}),
        content_type="application/json",
    )

    # Then: 422 复合结果同时返回已提交语义与最新 grant_failed 事实。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    body = _json_object(response.content)
    error = _json_dict(body, "error")
    details = error["details"]
    assert isinstance(details, dict)
    assert details["decision_committed"] is True
    assert details["status"] == "grant_failed"
    approval = details["approval"]
    assert isinstance(approval, dict)
    assert approval["id"] == access_request.id
    assert approval["status"] == "grant_failed"
    assert approval["decision_comment"] == "同意"
    access_request.refresh_from_db()
    assert access_request.status == "grant_failed"


def test_reject_requires_comment_and_applicant_sees_reason() -> None:
    # Given
    client, approver = logged_in_client("portal-rejecter")
    access_request = _submitted_request(
        "portal-reject-applicant",
        "portal-reject-app",
        approver_id=approver.authentik_user_id,
    )

    # When: 无意见驳回 422; 带意见驳回成功; 申请人查看自己的申请可见理由。
    missing_comment = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/reject",
        data=dumps({}),
        content_type="application/json",
    )
    rejected = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/reject",
        data=dumps({"comment": "范围过大, 请拆分"}),
        content_type="application/json",
    )
    applicant_client = _login_existing(access_request.user)
    my_requests = applicant_client.get("/portal/api/v1/me/access-requests")

    # Then
    my_body = _json_object(my_requests.content)
    assert missing_comment.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert rejected.status_code == HTTPStatus.OK
    requests_data = my_body["data"]
    assert isinstance(requests_data, list)
    first = requests_data[0]
    assert isinstance(first, dict)
    assert first["status"] == "rejected"
    assert first["decision_comment"] == "范围过大, 请拆分"


def test_non_approver_cannot_operate_or_view_detail() -> None:
    # Given: 与申请无关的登录用户。
    client, _user = logged_in_client("portal-outsider")
    access_request = _submitted_request(
        "portal-outsider-applicant",
        "portal-outsider-app",
        approver_id="someone-else",
    )

    # When
    pending = client.get("/portal/api/v1/me/approvals")
    detail = client.get(f"/portal/api/v1/me/approvals/{access_request.id}")
    approve = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/approve",
        data=dumps({}),
        content_type="application/json",
    )

    # Then: 列表为空、详情 404、操作 403。
    pending_body = _json_object(pending.content)
    assert pending_body["data"] == []
    assert detail.status_code == HTTPStatus.NOT_FOUND
    assert approve.status_code == HTTPStatus.FORBIDDEN
    access_request.refresh_from_db()
    assert access_request.status == "submitted"


def test_processed_filter_returns_my_decisions() -> None:
    # Given: 审批人已驳回一条申请。
    client, approver = logged_in_client("portal-history-approver")
    access_request = _submitted_request(
        "portal-history-applicant",
        "portal-history-app",
        approver_id=approver.authentik_user_id,
    )
    _ = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/reject",
        data=dumps({"comment": "驳回备案"}),
        content_type="application/json",
    )

    # When
    pending = client.get("/portal/api/v1/me/approvals?status=pending")
    processed = client.get("/portal/api/v1/me/approvals?status=processed")

    # Then
    pending_body = _json_object(pending.content)
    processed_body = _json_object(processed.content)
    assert pending_body["data"] == []
    processed_data = processed_body["data"]
    assert isinstance(processed_data, list)
    assert len(processed_data) == 1
    first = processed_data[0]
    assert isinstance(first, dict)
    assert first["decided_by"] == approver.authentik_user_id


def test_processed_approvals_count_and_slice_in_database() -> None:
    # Given: 审批人已有两条处理记录, 只读取第一页一条。
    client, approver = logged_in_client("portal-history-paged-approver")
    first_request = _submitted_request(
        "portal-history-paged-applicant-1",
        "portal-history-paged-app-1",
        approver_id=approver.authentik_user_id,
    )
    second_request = _submitted_request(
        "portal-history-paged-applicant-2",
        "portal-history-paged-app-2",
        approver_id=approver.authentik_user_id,
    )
    for access_request in (first_request, second_request):
        response = client.post(
            f"/portal/api/v1/me/approvals/{access_request.id}/reject",
            data=dumps({"comment": "分页测试"}),
            content_type="application/json",
        )
        assert response.status_code == HTTPStatus.OK

    # When
    with CaptureQueriesContext(connection) as captured:
        response = client.get(
            "/portal/api/v1/me/approvals?status=processed&page=1&page_size=1",
        )

    # Then: 主查询使用 COUNT 和 LIMIT, 不再先把全部处理记录加载进 Python。
    access_request_queries = [
        query["sql"]
        for query in captured.captured_queries
        if "access_requests_accessrequest" in query["sql"]
        and approver.authentik_user_id in query["sql"]
    ]
    assert response.status_code == HTTPStatus.OK
    assert any("COUNT(" in query for query in access_request_queries)
    assert any("LIMIT 1" in query for query in access_request_queries)
    body = _json_object(response.content)
    assert body["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 2,
        "total_pages": 2,
    }


def test_processed_approvals_clamp_page_to_last_page() -> None:
    # Given: 审批人已有两条处理记录, 每页一条。
    client, approver = logged_in_client("portal-history-clamped-approver")
    for index in range(2):
        access_request = _submitted_request(
            f"portal-history-clamped-applicant-{index}",
            f"portal-history-clamped-app-{index}",
            approver_id=approver.authentik_user_id,
        )
        response = client.post(
            f"/portal/api/v1/me/approvals/{access_request.id}/reject",
            data=dumps({"comment": "分页钳制测试"}),
            content_type="application/json",
        )
        assert response.status_code == HTTPStatus.OK

    # When: 请求远超总页数的页码。
    response = client.get(
        "/portal/api/v1/me/approvals?status=processed&page=999&page_size=1",
    )

    # Then: 服务端返回真实最后一页, 不暴露 page > total_pages 的矛盾信封。
    assert response.status_code == HTTPStatus.OK
    body = _json_object(response.content)
    data = body["data"]
    assert isinstance(data, list)
    assert len(data) == 1
    assert body["pagination"] == {
        "page": 2,
        "page_size": 1,
        "total_items": 2,
        "total_pages": 2,
    }


def _submitted_request(
    user_key: str,
    app_key: str,
    *,
    approver_id: str,
) -> AccessRequest:
    user = UserMirror.objects.create(authentik_user_id=user_key)
    app = App.objects.create(app_key=app_key, name=app_key)
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    group = AuthorizationGroup.objects.create(app=app, key="reader", kind="role", name="Reader")
    permission = Permission.objects.create(
        app=app,
        key="reader.view",
        name="Reader View",
        supported_scopes=[scope.key],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["rule-default-approver"],
    )
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        grant_type=GRANT_TYPE_PERMANENT,
        idempotency_key=f"{user_key}-submission",
        payload_digest="a" * 64,
    )
    approver, _created = UserMirror.objects.get_or_create(authentik_user_id=approver_id)
    _ = AccessRequestApprover.objects.create(
        access_request=access_request,
        approver=approver,
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    return access_request


def _login_existing(user: UserMirror) -> Client:
    client = Client()
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client


def _json_object(content: bytes) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(content)
    assert isinstance(parsed, dict), content.decode()
    return parsed


def _json_dict(body: dict[str, JsonValue], key: str) -> dict[str, JsonValue]:
    value = body[key]
    assert isinstance(value, dict)
    return value

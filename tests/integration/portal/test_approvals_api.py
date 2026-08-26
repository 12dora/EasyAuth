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
    REQUEST_STATUS_GRANT_CONFLICT,
    REQUEST_TYPE_CHANGE,
    AccessRequest,
    AccessRequestApprover,
    AccessRequestGroup,
    AccessRequestGroupGrantSnapshot,
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
from easyauth.grants.models import AccessGrant, AccessGrantGroup
from easyauth.grants.services import GrantMutationExpiredError
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


def test_approval_detail_uses_submitted_group_grant_snapshot() -> None:
    # Given: 申请提交时冻结了审批展示事实, 之后授权组头信息与当前 grants 都被替换。
    client, approver = logged_in_client("portal-snapshot-approver")
    access_request = _submitted_request(
        "portal-snapshot-applicant",
        "portal-snapshot-app",
        approver_id=approver.authentik_user_id,
    )
    group_link = AccessRequestGroup.objects.select_related("authorization_group").get(
        access_request=access_request,
    )
    group = group_link.authorization_group
    old_grant = AuthorizationGroupGrant.objects.get(authorization_group=group)
    old_grant.is_active = False
    old_grant.save(update_fields=["is_active"])
    group.kind = "bundle"
    group.name = "Renamed Reader"
    group.save(update_fields=["kind", "name"])
    new_permission = Permission.objects.create(
        app=access_request.app,
        key="reader.admin",
        name="Reader Admin",
        supported_scopes=["GLOBAL"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=new_permission,
        scope_key="GLOBAL",
    )

    # When: 审批人查看详情。
    detail = client.get(f"/portal/api/v1/me/approvals/{access_request.id}")

    # Then: 展示仍是提交时 snapshot, key/kind/name/grants 都不读 live group。
    assert detail.status_code == HTTPStatus.OK
    approval = _json_dict(_json_object(detail.content), "approval")
    authorization_groups = approval["authorization_groups"]
    assert isinstance(authorization_groups, list)
    assert authorization_groups[0] == {
        "key": "reader",
        "kind": "role",
        "name": "Reader",
        "grants": [
            {
                "permission": "reader.view",
                "permission_name": "Reader View",
                "scope": "GLOBAL",
            },
        ],
    }


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
    assert approval["reason"] == "跨部门工单处理"
    assert approval["decision_comment"] == "同意"
    assert approval["decided_by"] == approver.authentik_user_id
    assert isinstance(approval["decided_at"], str)
    access_request.refresh_from_db()
    assert access_request.status == "grant_failed"


def test_approve_base_revision_conflict_returns_409_and_requires_resubmission() -> None:
    # Given: lifecycle 申请待审批时绑定 base grant v1, 审批前当前授权已推进到 v2。
    client, approver = logged_in_client("portal-base-conflict-approver")
    access_request = _submitted_request(
        "portal-base-conflict-applicant",
        "portal-base-conflict-app",
        approver_id=approver.authentik_user_id,
    )
    group = AccessRequestGroup.objects.get(access_request=access_request).authorization_group
    grant = AccessGrant.objects.create(user=access_request.user, app=access_request.app)
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)
    access_request.request_type = REQUEST_TYPE_CHANGE
    access_request.base_grant = grant
    access_request.base_grant_revision = grant.version
    access_request.save(update_fields=["request_type", "base_grant", "base_grant_revision"])
    grant.version += 1
    grant.save(update_fields=["version", "updated_at"])

    # When: 审批人同意该旧 revision 申请。
    response = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/approve",
        data=dumps({"comment": "同意"}),
        content_type="application/json",
    )

    # Then: API 返回专用 409 冲突, 不伪装成可重试 grant_failed/422。
    assert response.status_code == HTTPStatus.CONFLICT
    body = _json_object(response.content)
    error = _json_dict(body, "error")
    assert error["code"] == "CONFLICT"
    details = error["details"]
    assert isinstance(details, dict)
    assert details["reason"] == "base_grant_revision_conflict"
    assert details["status"] == REQUEST_STATUS_GRANT_CONFLICT
    access_request.refresh_from_db()
    assert access_request.status == REQUEST_STATUS_GRANT_CONFLICT


def test_approve_expired_grant_returns_committed_decision_and_latest_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 审批人同意时, 限时授权已经过期。
    client, approver = logged_in_client("portal-expired-approver")
    access_request = _submitted_request(
        "portal-expired-applicant",
        "portal-expired-app",
        approver_id=approver.authentik_user_id,
    )

    def expire_grant_application(*_args: object, **_kwargs: object) -> None:
        raise GrantMutationExpiredError

    monkeypatch.setattr(
        "easyauth.access_requests.application.apply_grant_fact",
        expire_grant_application,
    )

    # When
    response = client.post(
        f"/portal/api/v1/me/approvals/{access_request.id}/approve",
        data=dumps({"comment": "同意"}),
        content_type="application/json",
    )

    # Then: API 返回稳定 409, 申请进入明确 grant_expired 终态。
    assert response.status_code == HTTPStatus.CONFLICT
    details = _json_dict(_json_dict(_json_object(response.content), "error"), "details")
    assert details["decision_committed"] is True
    assert details["status"] == "grant_expired"
    assert details["reason"] == "request_expired"
    access_request.refresh_from_db()
    assert access_request.status == "grant_expired"


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


def test_portal_approvals_honors_ordering_and_rejects_unknown_field() -> None:
    client, approver = logged_in_client("portal-order-approver")
    first = _submitted_request(
        "portal-order-applicant-z",
        "portal-order-app-z",
        approver_id=approver.authentik_user_id,
    )
    second = _submitted_request(
        "portal-order-applicant-a",
        "portal-order-app-a",
        approver_id=approver.authentik_user_id,
    )
    first.user.name = "Zoe"
    first.user.save(update_fields=["name"])
    second.user.name = "Ann"
    second.user.save(update_fields=["name"])

    default = client.get("/portal/api/v1/me/approvals")
    by_app = client.get("/portal/api/v1/me/approvals", {"ordering": "app_key"})
    by_applicant_desc = client.get("/portal/api/v1/me/approvals", {"ordering": "-applicant"})
    invalid = client.get("/portal/api/v1/me/approvals", {"ordering": "unknown"})

    assert _approval_ids(default.content) == [first.id, second.id]
    assert _approval_ids(by_app.content) == [second.id, first.id]
    assert _approval_ids(by_applicant_desc.content) == [first.id, second.id]
    assert invalid.status_code == HTTPStatus.BAD_REQUEST
    error = _json_object(invalid.content)["error"]
    assert isinstance(error, dict)
    assert error["code"] == "VALIDATION_ERROR"


def _approval_ids(content: bytes) -> list[int]:
    body = _json_object(content)
    data = body["data"]
    assert isinstance(data, list)
    result: list[int] = []
    for item in data:
        assert isinstance(item, dict)
        request_id = item["id"]
        assert isinstance(request_id, int)
        result.append(request_id)
    return result


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
        reason="跨部门工单处理",
        idempotency_key=f"{user_key}-submission",
        payload_digest="a" * 64,
    )
    approver, _created = UserMirror.objects.get_or_create(authentik_user_id=approver_id)
    _ = AccessRequestApprover.objects.create(
        access_request=access_request,
        approver=approver,
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    _ = AccessRequestGroupGrantSnapshot.objects.create(
        access_request=access_request,
        authorization_group_id_snapshot=group.id,
        authorization_group_key=group.key,
        authorization_group_kind=group.kind,
        authorization_group_name=group.name,
        permission_key=permission.key,
        permission_name=permission.name,
        scope_key=scope.key,
    )
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

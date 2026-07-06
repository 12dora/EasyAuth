from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.test import Client
from pydantic import TypeAdapter

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    AccessRequest,
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
    applicant = _json_dict(detail_body, "approval")["applicant"]
    assert isinstance(applicant, dict)
    assert applicant["user_id"] == "portal-applicant"
    approval = _json_dict(approved_body, "approval")
    assert approval["status"] == "grant_applied"
    assert AccessGrant.objects.filter(is_current=True).count() == 1


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
        approver_user_ids=[approver_id],
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

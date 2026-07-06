from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.access_requests.models import (
    GRANT_TYPE_PERMANENT,
    AccessRequest,
    AccessRequestGroup,
)
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
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-operations-approvals"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_admin_approves_on_behalf_with_audit() -> None:
    # Given: 超级管理员与一条待审批申请(审批人休假)。
    client = _logged_in_superuser("ops-approve-admin")
    access_request = _submitted_request("ops-approve-user", "ops-approve-app")

    # When: 管理员代审通过。
    response = client.post(
        f"/console/api/v1/operations/access-requests/{access_request.id}/approve",
        data=dumps({"comment": "审批人休假, 代审"}),
        content_type="application/json",
    )

    # Then: 授权生效, 审计 actor_type=console_admin。
    body = _response_json(response)
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    request_payload = body["access_request"]
    assert isinstance(request_payload, dict)
    assert request_payload["status"] == "grant_applied"
    assert access_request.decision_actor_type == "console_admin"
    assert AccessGrant.objects.filter(is_current=True).count() == 1
    audit_log = AuditLog.objects.get(event_type="access_request_approved")
    assert audit_log.actor_type == "console_admin"
    assert audit_log.actor_id == "ops-approve-admin"


def test_admin_rejects_with_comment_required() -> None:
    # Given
    client = _logged_in_superuser("ops-reject-admin")
    access_request = _submitted_request("ops-reject-user", "ops-reject-app")

    # When
    missing = client.post(
        f"/console/api/v1/operations/access-requests/{access_request.id}/reject",
        data=dumps({}),
        content_type="application/json",
    )
    rejected = client.post(
        f"/console/api/v1/operations/access-requests/{access_request.id}/reject",
        data=dumps({"comment": "目标权限过宽"}),
        content_type="application/json",
    )

    # Then
    access_request.refresh_from_db()
    assert missing.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert rejected.status_code == HTTPStatus.OK
    assert access_request.status == "rejected"
    assert access_request.decision_comment == "目标权限过宽"


def test_admin_reassigns_approvers() -> None:
    # Given
    client = _logged_in_superuser("ops-reassign-admin")
    access_request = _submitted_request("ops-reassign-user", "ops-reassign-app")
    _ = UserMirror.objects.create(authentik_user_id="ops-new-approver")

    # When
    response = client.post(
        f"/console/api/v1/operations/access-requests/{access_request.id}/reassign",
        data=dumps({"approver_user_ids": ["ops-new-approver"]}),
        content_type="application/json",
    )

    # Then
    access_request.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert access_request.approver_user_ids == ["ops-new-approver"]
    assert AuditLog.objects.filter(event_type="access_request_reassigned").exists()


def test_non_superuser_cannot_operate() -> None:
    # Given: 普通控制台用户。
    client = _logged_in_user("ops-plain-user")
    access_request = _submitted_request("ops-plain-applicant", "ops-plain-app")

    # When
    response = client.post(
        f"/console/api/v1/operations/access-requests/{access_request.id}/approve",
        data=dumps({}),
        content_type="application/json",
    )

    # Then
    assert response.status_code == HTTPStatus.FORBIDDEN
    access_request.refresh_from_db()
    assert access_request.status == "submitted"


def _submitted_request(user_key: str, app_key: str) -> AccessRequest:
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
        approver_user_ids=["vacationing-approver"],
    )
    _ = AccessRequestGroup.objects.create(access_request=access_request, authorization_group=group)
    return access_request


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar, Final

import pytest
from django.test import Client
from pydantic import BaseModel, ConfigDict

from easyauth.access_requests.models import AccessRequest
from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops3-contract"
ACCESS_REQUESTS_API_URL: Final = "/console/api/v1/operations/access-requests"
DEPENDENCY_HEALTH_API_URL: Final = "/console/api/v1/operations/dependency-health"


class _AccessRequestOperationItem(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: int
    approver_user_ids: tuple[str, ...]
    decided_by: str
    decision_actor_type: str
    decision_comment: str
    decided_at: str | None


class _AccessRequestsResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    data: tuple[_AccessRequestOperationItem, ...]


class _DependencyHealthComponent(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: str


class _DependencyHealthResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    authentik: _DependencyHealthComponent
    authentik_directory: _DependencyHealthComponent
    dingtalk: _DependencyHealthComponent
    celery: _DependencyHealthComponent


def test_ops3_access_requests_include_decision_fields() -> None:
    # Given: 一条待审批的运营申请(站内审批闭环, 与钉钉回调无关)。
    client = _logged_in_superuser("ops3-contract-access-admin")
    user = UserMirror.objects.create(authentik_user_id="ops3-contract-user")
    app = App.objects.create(app_key="ops3-contract-app", name="Contract App")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        reason="需要临时权限",
        approver_user_ids=["ops3-contract-approver"],
    )

    # When: 系统管理员查询 access-requests 运营列表。
    response = client.get(ACCESS_REQUESTS_API_URL, {"app_key": app.app_key})

    # Then: 响应包含审批决定字段, 并保留原有基础字段。
    body = _AccessRequestsResponse.model_validate_json(response.content)
    assert response.status_code == HTTPStatus.OK
    assert body.data[0].id == access_request.id
    assert body.data[0].approver_user_ids == ("ops3-contract-approver",)
    assert body.data[0].decided_by == ""
    assert body.data[0].decision_actor_type == ""
    assert body.data[0].decision_comment == ""
    assert body.data[0].decided_at is None


def test_ops3_dependency_health_read_writes_audit() -> None:
    # Given: 系统管理员准备读取 dependency health。
    client = _logged_in_superuser("ops3-contract-health-admin")

    # When: 系统管理员读取 dependency health API。
    response = client.get(DEPENDENCY_HEALTH_API_URL)

    # Then: API 返回健康列表并写入读取审计。
    body = _DependencyHealthResponse.model_validate_json(response.content)
    audit = AuditLog.objects.get(event_type="dependency_health_read")
    assert response.status_code == HTTPStatus.OK
    assert body.authentik.status == "unknown"
    assert body.authentik_directory.status == "unknown"
    assert body.dingtalk.status == "unknown"
    assert body.celery.status == "unknown"
    assert audit.actor_type == "admin"
    assert audit.actor_id == "ops3-contract-health-admin"
    assert audit.target_type == "dependency_health"


def _logged_in_superuser(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session["easyauth_authentik_groups"] = ["EasyAuth Admins"]
    session.save()
    return client

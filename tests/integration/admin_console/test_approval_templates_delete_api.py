from __future__ import annotations

from http import HTTPStatus
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.models import UserMirror
from easyauth.api.errors import JsonValue
from easyauth.applications.models import App
from easyauth.workflows.models import ApprovalInstance, ApprovalTemplate

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-approval-templates-delete-api"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_superuser_deletes_unreferenced_approval_template() -> None:
    # Given: 平台层审批模板, 未被任何审批实例引用。
    client = _logged_in_superuser("approval-delete-admin")
    template = ApprovalTemplate.objects.create(
        app=None,
        key="unused-template",
        name="未引用模板",
        dingtalk_process_code="PROC-UNUSED",
    )

    # When: 从表格操作列删除。
    response = client.delete(f"/console/api/v1/approval-templates/{template.id}")

    # Then
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    assert body["deleted"] is True
    assert not ApprovalTemplate.objects.filter(id=template.id).exists()


def test_delete_blocked_when_template_referenced_by_instance() -> None:
    # Given: 一个已被审批实例引用的模板(instances=PROTECT)。
    client = _logged_in_superuser("approval-delete-protected-admin")
    app = App.objects.create(app_key="approval-del-crm", name="CRM")
    originator = UserMirror.objects.create(authentik_user_id="approval-del-user")
    template = ApprovalTemplate.objects.create(
        app=app,
        key="referenced-template",
        name="被引用模板",
        dingtalk_process_code="PROC-REF",
    )
    _ = ApprovalInstance.objects.create(
        app=app,
        template=template,
        biz_key="biz-1",
        originator_user=originator,
    )

    # When: 尝试删除。
    response = client.delete(f"/console/api/v1/approval-templates/{template.id}")

    # Then: 返回 409 冲突, 模板仍在。
    assert response.status_code == HTTPStatus.CONFLICT
    assert ApprovalTemplate.objects.filter(id=template.id).exists()


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed

from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import JsonValue
from easyauth.lifecycle.models import OnboardingTemplate
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-onboarding-templates-api"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_superuser_toggles_onboarding_template_status() -> None:
    # Given: 一个启用中的岗位模板。
    client = _logged_in_superuser("onboarding-toggle-admin")
    template = OnboardingTemplate.objects.create(name="入职模板-停用", is_active=True)

    # When: 表格操作列切换启停(body 只含 is_active, 不重建模板项)。
    disabled = client.patch(
        f"/console/api/v1/lifecycle/onboarding-templates/{template.id}",
        data=dumps({"is_active": False}),
        content_type="application/json",
    )
    template.refresh_from_db()

    # Then: 仅状态被更新。
    body = _response_json(disabled)
    assert disabled.status_code == HTTPStatus.OK
    assert template.is_active is False
    payload = body["onboarding_template"]
    assert isinstance(payload, dict)
    assert payload["is_active"] is False

    # And: 可再次启用。
    enabled = client.patch(
        f"/console/api/v1/lifecycle/onboarding-templates/{template.id}",
        data=dumps({"is_active": True}),
        content_type="application/json",
    )
    template.refresh_from_db()
    assert enabled.status_code == HTTPStatus.OK
    assert template.is_active is True


def test_superuser_delete_onboarding_template_is_blocked_after_creation() -> None:
    # Given: API 创建模板后会生成不可变 current revision。
    client = _logged_in_superuser("onboarding-delete-admin")
    created = client.post(
        "/console/api/v1/lifecycle/onboarding-templates",
        data=dumps({"name": "入职模板-删除禁用", "description": "", "items": []}),
        content_type="application/json",
    )
    created_body = _response_json(created)
    payload = created_body["onboarding_template"]
    assert isinstance(payload, dict)
    template_id = payload["id"]
    assert isinstance(template_id, int)

    # When: 旧删除入口被调用。
    response = client.delete(
        f"/console/api/v1/lifecycle/onboarding-templates/{template_id}",
    )

    # Then: 返回稳定冲突, 不触发模板修订级联删除。
    body = _response_json(response)
    assert response.status_code == HTTPStatus.CONFLICT
    assert "请改为停用" in str(body)
    assert OnboardingTemplate.objects.filter(id=template_id).exists()


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    _ = authenticate_console_admin(client, username)
    return client


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed

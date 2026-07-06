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


def test_superuser_deletes_onboarding_template() -> None:
    # Given
    client = _logged_in_superuser("onboarding-delete-admin")
    template = OnboardingTemplate.objects.create(name="入职模板-删除")

    # When: 从表格操作列删除。
    response = client.delete(
        f"/console/api/v1/lifecycle/onboarding-templates/{template.id}",
    )

    # Then
    body = _response_json(response)
    assert response.status_code == HTTPStatus.OK
    assert body["deleted"] is True
    assert not OnboardingTemplate.objects.filter(id=template.id).exists()


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _response_json(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed

from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import JsonValue
from easyauth.applications.models import App, AppMembership, OAuthClientBinding
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-login"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_credentials_api_disables_oauth_client_without_deleting_history() -> None:
    # Given: owner 管理一个 active OAuth client。
    client = _logged_in_client("owner-ops1-oauth-api-disable")
    app = _owned_app("ops1-oauth-api-disable", "owner-ops1-oauth-api-disable")
    created = client.post(
        _credentials_api_url(app.app_key, "oauth-clients"),
        data=dumps({"name": "oauth disable"}),
        content_type="application/json",
    )
    credential = _json_object(_json_dict(created)["credential"])
    credential_id = _json_int(credential["id"])

    # When: owner 通过通用 disable API 禁用 OAuth client。
    response = client.post(
        _credentials_api_url(app.app_key, f"oauth-clients/{credential_id}/disable"),
        data=dumps({"reason": "停用试点接入"}),
        content_type="application/json",
    )

    # Then: API 标记 binding inactive, 保留 OAuth application 和审计 reason。
    binding = OAuthClientBinding.objects.get(id=credential_id)
    response_credential = _json_object(_json_dict(response)["credential"])
    audit = AuditLog.objects.get(event_type="console_oauth_client_disabled")
    assert response.status_code == HTTPStatus.OK
    assert response_credential["is_active"] is False
    assert binding.is_active is False
    assert OAuthClientBinding.objects.filter(
        id=credential_id,
        oauth_application__isnull=False,
    ).exists()
    assert audit.metadata["reason"] == "停用试点接入"


def _owned_app(app_key: str, owner_user_id: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=owner_user_id, role="owner")
    return app


def _logged_in_client(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _credentials_api_url(app_key: str, suffix: str = "") -> str:
    base_url = f"/console/api/v1/apps/{app_key}/credentials"
    if not suffix:
        return base_url
    return f"{base_url}/{suffix}"


def _json_dict(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed


def _json_object(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict), value
    return value


def _json_int(value: JsonValue) -> int:
    assert isinstance(value, int), value
    return value

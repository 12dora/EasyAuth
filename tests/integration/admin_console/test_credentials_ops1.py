from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppCredential, AppMembership
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-login"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_console_static_token_create_displays_plaintext_only_once() -> None:
    # Given: 应用负责人管理一个 App。
    client = _logged_in_client("owner-ops1-token-create")
    app = _owned_app("ops1-token-create", "owner-ops1-token-create")

    # When: owner 通过 private API 创建静态 app token。
    response = client.post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps({"name": "primary integration"}),
        content_type="application/json",
    )

    # Then: 明文 token 只出现在本次 API 响应, 不进入审计 metadata 或后续列表。
    body = response.content.decode()
    payload = _json_dict(response)
    plaintext_token = _json_string(_json_object(payload["one_time_secret"])["app_token"])
    credential = AppCredential.objects.get(app=app)
    assert response.status_code == HTTPStatus.CREATED
    assert plaintext_token in body
    assert plaintext_token not in credential.token_hash
    for audit_log in AuditLog.objects.all():
        assert plaintext_token not in str(audit_log.metadata)
    followup = client.get(_credentials_api_url(app.app_key))
    assert plaintext_token not in followup.content.decode()


def test_ops1_console_static_token_disable_makes_public_api_fail_safely() -> None:
    # Given: App 已经有一个可用静态 token。
    client = _logged_in_client("owner-ops1-token-disable")
    app = _owned_app("ops1-token-disable", "owner-ops1-token-disable")
    issue = StaticTokenService.create_token(app=app, name="primary integration")

    # When: owner 通过 private API 禁用该 token。
    response = client.post(
        _credentials_api_url(app.app_key, f"static-tokens/{issue.credential_id}/disable"),
        content_type="application/json",
    )
    api_response = Client().get(
        f"/api/v1/apps/{app.app_key}/users/some-user/permissions",
        HTTP_AUTHORIZATION=f"Bearer {issue.plaintext_token}",
    )

    # Then: private API 返回成功, 公共权限查询 API 对禁用凭据返回 401。
    assert response.status_code == HTTPStatus.OK
    assert api_response.status_code == HTTPStatus.UNAUTHORIZED
    assert AppCredential.objects.get(id=issue.credential_id).is_active is False


def test_ops1_console_oauth_client_secret_is_one_time_and_not_visible_to_developer() -> None:
    # Given: owner 和 developer 都关联同一个 App。
    owner_client = _logged_in_client("owner-ops1-oauth")
    developer_client = _logged_in_client("developer-ops1-oauth")
    app = _owned_app("ops1-oauth", "owner-ops1-oauth")
    _ = AppMembership.objects.create(app=app, user_id="developer-ops1-oauth", role="developer")

    # When: owner 通过 private API 创建 OAuth2 client credentials, developer 尝试创建静态 token。
    owner_response = owner_client.post(
        _credentials_api_url(app.app_key, "oauth-clients"),
        data=dumps({"name": "oauth integration"}),
        content_type="application/json",
    )
    developer_response = developer_client.post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps({"name": "developer attempt"}),
        content_type="application/json",
    )

    # Then: OAuth secret 只在 owner API 响应出现一次, developer 被拒绝操作凭据。
    owner_body = _json_dict(owner_response)
    client_secret = _json_string(_json_object(owner_body["one_time_secret"])["client_secret"])
    assert owner_response.status_code == HTTPStatus.CREATED
    assert developer_response.status_code == HTTPStatus.FORBIDDEN
    assert client_secret not in owner_client.get(_credentials_api_url(app.app_key)).content.decode()
    for audit_log in AuditLog.objects.all():
        assert client_secret not in str(audit_log.metadata)
    assert AppCredential.objects.filter(app=app, name="developer attempt").exists() is False


def test_ops1_credentials_api_owner_lists_without_secret_material() -> None:
    # Given: owner 管理一个同时具备静态 token 和 OAuth client 的 App。
    client = _logged_in_client("owner-ops1-credentials-list-api")
    app = _owned_app("ops1-credentials-list-api", "owner-ops1-credentials-list-api")
    static_issue = StaticTokenService.create_token(app=app, name="primary integration")
    oauth_response = client.post(
        _credentials_api_url(app.app_key, "oauth-clients"),
        data=dumps({"name": "oauth integration"}),
        content_type="application/json",
    )
    oauth_body = _json_dict(oauth_response)
    oauth_credential = _json_object(oauth_body["credential"])
    oauth_secret = _json_object(oauth_body["one_time_secret"])
    client_secret = _json_string(oauth_secret["client_secret"])
    token_hash = AppCredential.objects.get(id=static_issue.credential_id).token_hash

    # When: owner 查询凭据列表。
    response = client.get(_credentials_api_url(app.app_key))

    # Then: API 返回凭据元数据, 但不泄漏 token hash、静态 token 明文或 OAuth secret。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert _json_dict(response)["items"] == [
        {
            "id": static_issue.credential_id,
            "kind": "static_token",
            "name": "primary integration",
            "is_active": True,
        },
        {
            "id": _json_int(oauth_credential["id"]),
            "kind": "oauth_client",
            "name": "oauth integration",
            "is_active": True,
            "client_id": _json_string(oauth_secret["client_id"]),
        },
    ]
    assert static_issue.plaintext_token not in body
    assert token_hash not in body
    assert client_secret not in body


def test_ops1_credentials_api_creates_static_token_with_one_time_plaintext() -> None:
    # Given: owner 管理一个没有凭据的 App。
    client = _logged_in_client("owner-ops1-static-api-create")
    app = _owned_app("ops1-static-api-create", "owner-ops1-static-api-create")

    # When: owner 通过 private API 创建静态 token。
    response = client.post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps({"name": "api token"}),
        content_type="application/json",
    )

    # Then: 本次响应包含一次性明文 token, 列表和存储层不暴露明文或 hash。
    body = response.content.decode()
    response_body = _json_dict(response)
    plaintext_token = _json_string(_json_object(response_body["one_time_secret"])["app_token"])
    credential = AppCredential.objects.get(app=app)
    list_response = client.get(_credentials_api_url(app.app_key))
    assert response.status_code == HTTPStatus.CREATED
    assert response_body["credential"] == {
        "id": credential.id,
        "kind": "static_token",
        "name": "api token",
        "is_active": True,
    }
    assert plaintext_token.startswith("eat_")
    assert plaintext_token not in credential.token_hash
    assert credential.token_hash not in body
    assert plaintext_token not in list_response.content.decode()
    assert credential.token_hash not in list_response.content.decode()


def test_ops1_credentials_api_rotates_static_token_with_one_time_plaintext() -> None:
    # Given: owner 管理一个已有静态 token 的 App。
    client = _logged_in_client("owner-ops1-static-api-rotate")
    app = _owned_app("ops1-static-api-rotate", "owner-ops1-static-api-rotate")
    original = StaticTokenService.create_token(app=app, name="rotated token")

    # When: owner 轮换静态 token。
    response = client.post(
        _credentials_api_url(app.app_key, f"static-tokens/{original.credential_id}/rotate"),
        content_type="application/json",
    )

    # Then: API 返回新凭据和新明文 token, 新旧 token 不相同。
    response_body = _json_dict(response)
    new_token = _json_string(_json_object(response_body["one_time_secret"])["app_token"])
    assert response.status_code == HTTPStatus.CREATED
    credential = _json_object(response_body["credential"])
    assert credential["kind"] == "static_token"
    assert credential["name"] == "rotated token"
    assert new_token.startswith("eat_")
    assert new_token != original.plaintext_token


def test_ops1_credentials_api_disables_static_token() -> None:
    # Given: owner 管理一个 active 静态 token。
    client = _logged_in_client("owner-ops1-static-api-disable")
    app = _owned_app("ops1-static-api-disable", "owner-ops1-static-api-disable")
    issue = StaticTokenService.create_token(app=app, name="disable token")

    # When: owner 禁用该静态 token。
    response = client.post(
        _credentials_api_url(app.app_key, f"static-tokens/{issue.credential_id}/disable"),
        content_type="application/json",
    )

    # Then: API 返回禁用后的凭据元数据, 数据库状态同步为 inactive。
    credential = AppCredential.objects.get(id=issue.credential_id)
    assert response.status_code == HTTPStatus.OK
    assert _json_dict(response)["credential"] == {
        "id": issue.credential_id,
        "kind": "static_token",
        "name": "disable token",
        "is_active": False,
    }
    assert credential.is_active is False


def test_ops1_credentials_api_creates_oauth_client_with_one_time_secret() -> None:
    # Given: owner 管理一个 App。
    client = _logged_in_client("owner-ops1-oauth-api-create")
    app = _owned_app("ops1-oauth-api-create", "owner-ops1-oauth-api-create")

    # When: owner 创建 OAuth client credentials。
    response = client.post(
        _credentials_api_url(app.app_key, "oauth-clients"),
        data=dumps({"name": "oauth api"}),
        content_type="application/json",
    )

    # Then: 本次响应包含 client_id/client_secret, 后续列表只保留 client_id。
    list_response = client.get(_credentials_api_url(app.app_key))
    response_body = _json_dict(response)
    one_time_secret = _json_object(response_body["one_time_secret"])
    secret = _json_string(one_time_secret["client_secret"])
    assert response.status_code == HTTPStatus.CREATED
    assert _json_object(response_body["credential"])["kind"] == "oauth_client"
    assert _json_string(one_time_secret["client_id"])
    assert secret
    assert secret not in list_response.content.decode()


def test_ops1_credentials_api_developer_write_is_forbidden() -> None:
    # Given: developer 可见 App, 但不是 owner。
    client = _logged_in_client("developer-ops1-credentials-api")
    app = App.objects.create(app_key="ops1-credentials-dev-api", name="Dev API")
    _ = AppMembership.objects.create(
        app=app,
        user_id="developer-ops1-credentials-api",
        role="developer",
    )

    # When: developer 尝试创建静态 token。
    response = client.post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps({"name": "developer token"}),
        content_type="application/json",
    )

    # Then: API 拒绝写操作且不创建凭据。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_object(_json_dict(response)["error"])["code"] == ErrorCode.PERMISSION_DENIED
    assert AppCredential.objects.filter(app=app).exists() is False


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


def _json_string(value: JsonValue) -> str:
    assert isinstance(value, str), value
    return value


def _json_int(value: JsonValue) -> int:
    assert isinstance(value, int), value
    return value

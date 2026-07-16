from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
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
    assert _json_dict(response)["data"] == [
        {
            "id": static_issue.credential_id,
            "kind": "static_token",
            "name": "primary integration",
            "is_active": True,
            "capabilities": [],
        },
        {
            "id": _json_int(oauth_credential["id"]),
            "kind": "oauth_client",
            "name": "oauth integration",
            "is_active": True,
            "client_id": _json_string(oauth_secret["client_id"]),
            "capabilities": [],
        },
    ]
    assert static_issue.plaintext_token not in body
    assert token_hash not in body
    assert client_secret not in body


def test_ops1_credentials_api_returns_401_when_listing_without_login() -> None:
    # Given: App 已存在 active 静态 token。
    app = _owned_app("ops1-credentials-list-unauth", "owner-ops1-list-unauth")
    issue = StaticTokenService.create_token(app=app, name="existing token")

    # When: 未登录用户查询凭据列表。
    response = Client(HTTP_HOST="localhost").get(_credentials_api_url(app.app_key))

    # Then: API 返回 401, 且不修改已有凭据。
    credential = AppCredential.objects.get(id=issue.credential_id)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert credential.is_active is True
    assert AppCredential.objects.filter(app=app).count() == 1


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
        "capabilities": [],
    }
    assert plaintext_token.startswith("eat_")
    assert plaintext_token not in credential.token_hash
    assert credential.token_hash not in body
    assert plaintext_token not in list_response.content.decode()
    assert credential.token_hash not in list_response.content.decode()


def test_ops1_credentials_api_returns_401_when_creating_static_token_without_login() -> None:
    # Given: App 已存在且没有凭据。
    app = _owned_app("ops1-static-api-create-unauth", "owner-ops1-create-unauth")

    # When: 未登录用户尝试创建静态 token。
    response = Client(HTTP_HOST="localhost").post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps({"name": "api token"}),
        content_type="application/json",
    )

    # Then: API 返回 401, 且不创建凭据。
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert AppCredential.objects.filter(app=app).exists() is False


@pytest.mark.parametrize(
    ("payload", "case_id"),
    [
        ({"name": ""}, "blank-name"),
        ({"name": "valid token", "unexpected": "field"}, "extra-field"),
        ({"name": "x" * 129}, "overlong-name"),
    ],
    ids=["blank-name", "extra-field", "overlong-name"],
)
def test_ops1_credentials_api_rejects_invalid_static_token_create_payload(
    payload: dict[str, str],
    case_id: str,
) -> None:
    # Given: owner 管理一个没有凭据的 App。
    client = _logged_in_client(f"owner-ops1-static-api-invalid-{case_id}")
    app = _owned_app(
        f"ops1-static-api-invalid-{case_id}",
        f"owner-ops1-static-api-invalid-{case_id}",
    )

    # When: owner 使用非法 payload 创建静态 token。
    response = client.post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps(payload),
        content_type="application/json",
    )

    # Then: API 返回输入错误, 且不创建凭据。
    assert response.status_code in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY}
    assert AppCredential.objects.filter(app=app).exists() is False


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


def test_ops1_credentials_api_returns_401_when_rotating_static_token_without_login() -> None:
    # Given: App 已存在 active 静态 token。
    app = _owned_app("ops1-static-api-rotate-unauth", "owner-ops1-rotate-unauth")
    original = StaticTokenService.create_token(app=app, name="rotated token")

    # When: 未登录用户尝试轮换静态 token。
    response = Client(HTTP_HOST="localhost").post(
        _credentials_api_url(app.app_key, f"static-tokens/{original.credential_id}/rotate"),
        content_type="application/json",
    )

    # Then: API 返回 401, 且不创建新凭据、不停用原凭据。
    credential = AppCredential.objects.get(id=original.credential_id)
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert credential.is_active is True
    assert AppCredential.objects.filter(app=app).count() == 1


def test_ops1_credentials_api_returns_403_when_developer_rotates_static_token() -> None:
    # Given: developer 可见 App, App 已存在 active 静态 token。
    client = _logged_in_client("developer-ops1-credentials-rotate")
    app = App.objects.create(app_key="ops1-credentials-dev-rotate", name="Dev Rotate")
    _ = AppMembership.objects.create(
        app=app,
        user_id="developer-ops1-credentials-rotate",
        role="developer",
    )
    original = StaticTokenService.create_token(app=app, name="developer rotate")

    # When: developer 尝试轮换静态 token。
    response = client.post(
        _credentials_api_url(app.app_key, f"static-tokens/{original.credential_id}/rotate"),
        content_type="application/json",
    )

    # Then: API 拒绝写操作且不修改凭据。
    credential = AppCredential.objects.get(id=original.credential_id)
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert _json_object(_json_dict(response)["error"])["code"] == ErrorCode.PERMISSION_DENIED
    assert credential.is_active is True
    assert AppCredential.objects.filter(app=app).count() == 1


def test_ops1_credentials_api_returns_404_when_owner_rotates_other_app_static_token() -> None:
    # Given: owner 管理当前 App, 另一个 App 拥有 active 静态 token。
    client = _logged_in_client("owner-ops1-credentials-rotate-cross-app")
    app = _owned_app("ops1-credentials-rotate-own-app", "owner-ops1-credentials-rotate-cross-app")
    other_app = _owned_app(
        "ops1-credentials-rotate-other-app",
        "owner-ops1-credentials-rotate-other",
    )
    target = StaticTokenService.create_token(app=other_app, name="other app token")

    # When: owner 在当前 App 路径下轮换其他 App 的 credential_id。
    response = client.post(
        _credentials_api_url(app.app_key, f"static-tokens/{target.credential_id}/rotate"),
        content_type="application/json",
    )

    # Then: API 返回 404, 目标凭据仍为 active。
    credential = AppCredential.objects.get(id=target.credential_id)
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert credential.is_active is True
    assert AppCredential.objects.filter(app=other_app).count() == 1


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
        "capabilities": [],
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


def test_credential_capabilities_create_rotate_and_owner_update() -> None:
    client = _logged_in_client("owner-credential-capabilities")
    app = _owned_app("credential-capabilities", "owner-credential-capabilities")
    created = client.post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps({"name": "notify token", "capabilities": ["notify"]}),
        content_type="application/json",
    )
    created_item = _json_object(_json_dict(created)["credential"])
    credential_id = _json_int(created_item["id"])
    assert created.status_code == HTTPStatus.CREATED
    assert created_item["capabilities"] == ["notify"]

    rotated = client.post(
        _credentials_api_url(app.app_key, f"static-tokens/{credential_id}/rotate"),
        content_type="application/json",
    )
    rotated_item = _json_object(_json_dict(rotated)["credential"])
    assert rotated.status_code == HTTPStatus.CREATED
    assert rotated_item["capabilities"] == ["notify"]

    updated = client.patch(
        _credentials_api_url(
            app.app_key,
            f"static-tokens/{credential_id}/capabilities",
        ),
        data=dumps({"capabilities": ["notify", "directory"]}),
        content_type="application/json",
    )
    assert updated.status_code == HTTPStatus.OK
    assert _json_object(_json_dict(updated)["credential"])["capabilities"] == [
        "directory",
        "notify",
    ]
    audit = AuditLog.objects.filter(
        event_type="console_credential_capabilities_updated",
    ).get()
    assert audit.metadata["capabilities"] == ["directory", "notify"]


def test_oauth_capabilities_update_is_owner_only() -> None:
    owner = _logged_in_client("owner-oauth-capabilities")
    developer = _logged_in_client("developer-oauth-capabilities")
    app = _owned_app("oauth-capabilities", "owner-oauth-capabilities")
    _ = AppMembership.objects.create(
        app=app,
        user_id="developer-oauth-capabilities",
        role="developer",
    )
    created = owner.post(
        _credentials_api_url(app.app_key, "oauth-clients"),
        data=dumps({"name": "directory client", "capabilities": ["directory"]}),
        content_type="application/json",
    )
    credential_id = _json_int(_json_object(_json_dict(created)["credential"])["id"])
    url = _credentials_api_url(app.app_key, f"oauth-clients/{credential_id}/capabilities")
    denied = developer.put(
        url,
        data=dumps({"capabilities": ["notify"]}),
        content_type="application/json",
    )
    assert denied.status_code == HTTPStatus.FORBIDDEN
    updated = owner.put(
        url,
        data=dumps({"capabilities": ["notify"]}),
        content_type="application/json",
    )
    assert updated.status_code == HTTPStatus.OK
    assert _json_object(_json_dict(updated)["credential"])["capabilities"] == ["notify"]


@pytest.mark.parametrize(
    "capabilities",
    [["unknown"], ["notify", "notify"]],
    ids=["unknown", "duplicate"],
)
def test_credential_capabilities_reject_invalid_values(capabilities: list[str]) -> None:
    client = _logged_in_client(f"owner-invalid-capabilities-{len(capabilities)}")
    app = _owned_app(
        f"invalid-capabilities-{len(capabilities)}",
        f"owner-invalid-capabilities-{len(capabilities)}",
    )
    response = client.post(
        _credentials_api_url(app.app_key, "static-tokens"),
        data=dumps({"name": "invalid", "capabilities": capabilities}),
        content_type="application/json",
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert AppCredential.objects.filter(app=app).exists() is False


def _owned_app(app_key: str, owner_user_id: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=owner_user_id, role="owner")
    return app


def _logged_in_client(username: str) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
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

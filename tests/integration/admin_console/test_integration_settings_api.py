from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.applications.integration_settings import IntegrationSettings

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

SETTINGS_API_URL: Final = "/console/api/v1/settings/integrations"


def test_integration_settings_get_returns_env_fallback() -> None:
    client = _logged_in_superuser("settings-get-admin")

    response = client.get(SETTINGS_API_URL)

    assert response.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["authentik_base_url_override"] == ""
    assert payload["authentik_base_url_source"] == "env"
    assert payload["authentik_base_url_effective"] == "http://localhost:19000"


def test_integration_settings_put_sets_override_and_hides_token() -> None:
    client = _logged_in_superuser("settings-put-admin")

    response = client.put(
        SETTINGS_API_URL,
        data={
            "authentik_base_url": "https://auth.jiefakj.com/",
            "authentik_api_token": "ak-secret-token",
        },
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    body = response.content.decode()
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["authentik_base_url_override"] == "https://auth.jiefakj.com"
    assert payload["authentik_base_url_effective"] == "https://auth.jiefakj.com"
    assert payload["authentik_base_url_source"] == "override"
    assert payload["authentik_api_token_configured"] is True
    assert payload["authentik_api_token_source"] == "override"  # noqa: S105 - 配置来源标记, 非凭据.
    assert payload["updated_by"] == "settings-put-admin"
    assert "ak-secret-token" not in body

    row = IntegrationSettings.objects.get(pk=1)
    assert row.authentik_base_url == "https://auth.jiefakj.com"
    assert row.authentik_api_token == "ak-secret-token"  # noqa: S105 - 测试用假 token.


def test_integration_settings_token_is_encrypted_at_rest() -> None:
    # Given: 管理员保存了 Authentik 管理 token。
    client = _logged_in_superuser("settings-encrypt-admin")
    response = client.put(
        SETTINGS_API_URL,
        data={
            "authentik_base_url": "https://auth.jiefakj.com/",
            "authentik_api_token": "ak-plaintext-secret",
        },
        content_type="application/json",
    )
    assert response.status_code == HTTPStatus.OK

    # Then: 数据库列里是密文, 而 ORM 读取透明解密回明文。
    from django.db import connection  # noqa: PLC0415 - 用例内直读原始列.

    table = IntegrationSettings._meta.db_table  # noqa: SLF001 - 读取列名.
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT authentik_api_token FROM {table} WHERE id = 1")  # noqa: S608
        stored = cursor.fetchone()[0]
    assert stored != "ak-plaintext-secret"
    assert "ak-plaintext-secret" not in stored
    decrypted = IntegrationSettings.load().authentik_api_token
    assert decrypted == "ak-plaintext-secret"


def test_integration_settings_rejects_plaintext_http_base_url() -> None:
    # Given: 管理员尝试把 base_url 配成明文 http 的非本地地址。
    client = _logged_in_superuser("settings-http-admin")

    # When: 保存该配置。
    response = client.put(
        SETTINGS_API_URL,
        data={"authentik_base_url": "http://auth.internal.example"},
        content_type="application/json",
    )

    # Then: 被拒绝, 不落库明文 http, 避免管理 token 明文传输。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert IntegrationSettings.load().authentik_base_url == ""


def test_integration_settings_put_keeps_token_when_omitted() -> None:
    client = _logged_in_superuser("settings-keep-admin")
    row = IntegrationSettings.load()
    row.authentik_api_token = "existing-token"  # noqa: S105 - 测试用假 token.
    row.save()

    response = client.put(
        SETTINGS_API_URL,
        data={"authentik_base_url": "https://auth.example.com"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    row.refresh_from_db()
    assert row.authentik_api_token == "existing-token"  # noqa: S105 - 测试用假 token.
    assert row.authentik_base_url == "https://auth.example.com"


def test_integration_settings_put_keeps_authentik_when_only_dingtalk_fields_are_sent() -> None:
    client = _logged_in_superuser("settings-dingtalk-admin")
    row = IntegrationSettings.load()
    row.authentik_base_url = "https://auth.example.com"
    row.authentik_api_token = "existing-token"  # noqa: S105 - 测试用假 token.
    row.save()

    response = client.put(
        SETTINGS_API_URL,
        data={"dingtalk_app_key": "ding-app", "dingtalk_agent_id": "12345"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    row.refresh_from_db()
    assert row.authentik_base_url == "https://auth.example.com"
    assert row.authentik_api_token == "existing-token"  # noqa: S105 - 测试用假 token.
    assert row.dingtalk_app_key == "ding-app"
    assert row.dingtalk_agent_id == "12345"


def test_integration_settings_put_can_explicitly_clear_authentik_base_url() -> None:
    client = _logged_in_superuser("settings-clear-base-url-admin")
    row = IntegrationSettings.load()
    row.authentik_base_url = "https://auth.example.com"
    row.save()

    response = client.put(
        SETTINGS_API_URL,
        data={"authentik_base_url": ""},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK
    row.refresh_from_db()
    assert row.authentik_base_url == ""


def test_integration_settings_put_rejects_invalid_url() -> None:
    client = _logged_in_superuser("settings-invalid-admin")

    response = client.put(
        SETTINGS_API_URL,
        data={"authentik_base_url": "ftp://auth.example.com"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_integration_settings_requires_superuser() -> None:
    _ = UserMirror.objects.create(authentik_user_id="settings-normal-user")
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = "settings-normal-user"
    session["easyauth_authentik_groups"] = ["Employees"]
    session.save()

    response = client.get(SETTINGS_API_URL)

    assert response.status_code == HTTPStatus.FORBIDDEN


def _logged_in_superuser(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session["easyauth_authentik_groups"] = ["EasyAuth Admins"]
    session.save()
    return client

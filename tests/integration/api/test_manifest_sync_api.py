from __future__ import annotations

import json
from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client

from easyauth.applications.models import App, PermissionTemplateVersion
from easyauth.applications.services import StaticTokenService
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db

_URL: Final = "/api/v1/apps/{app_key}/manifest-sync"


def _app_with_token(app_key: str) -> tuple[App, str]:
    app = App.objects.create(app_key=app_key, name=app_key)
    issue = StaticTokenService.create_token(app=app, name="integration")
    return app, issue.plaintext_token


def _manifest(app_key: str, schema_version: int, *, permission_name: str = "查看订单") -> dict:
    return {
        "schema_version": schema_version,
        "app": {"app_key": app_key, "name": "EasyTrade"},
        "scopes": [{"key": "SELF", "name": "本人"}],
        "permission_groups": [{"key": "order", "name": "订单"}],
        "permissions": [
            {
                "key": "order.view",
                "name": permission_name,
                "group_key": "order",
                "supported_scopes": ["SELF"],
            },
        ],
        "lifecycle": {
            "handover_url": "/api/v1/easyauth/lifecycle/handover",
            "onboard_url": None,
            "capabilities": ["preview"],
        },
        "webhook": {"signing": "hmac-sha256"},
    }


def _post(client: Client, app_key: str, token: str, body: dict) -> object:
    return client.post(
        _URL.format(app_key=app_key),
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )


def test_manifest_sync_applies_new_version_and_autofills_webhook() -> None:
    # Given: 已注册应用与静态 token。
    app, token = _app_with_token("sync-crm")

    # When: 下游推送 manifest(带 base_url 供相对路径补全)。
    response = _post(
        client=Client(),
        app_key=app.app_key,
        token=token,
        body={"manifest": _manifest(app.app_key, 1), "base_url": "https://etrade.example.com"},
    )

    # Then: 导入成功, 版本落库, webhook 交接 URL 由 manifest 补全。
    assert response.status_code == HTTPStatus.OK
    payload = response.json()
    assert payload["already_up_to_date"] is False
    assert payload["template_version"] == 1
    assert PermissionTemplateVersion.objects.filter(app=app, version=1).exists()
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == "https://etrade.example.com/api/v1/easyauth/lifecycle/handover"
    assert config.updated_by == "manifest"


def test_manifest_sync_same_content_is_idempotent() -> None:
    app, token = _app_with_token("sync-idem")
    client = Client()
    first = _post(client, app.app_key, token, {"manifest": _manifest(app.app_key, 1)})
    assert first.status_code == HTTPStatus.OK

    second = _post(client, app.app_key, token, {"manifest": _manifest(app.app_key, 1)})

    assert second.status_code == HTTPStatus.OK
    assert second.json()["already_up_to_date"] is True


def test_manifest_sync_conflicts_without_version_bump() -> None:
    app, token = _app_with_token("sync-conflict")
    client = Client()
    assert _post(client, app.app_key, token, {"manifest": _manifest(app.app_key, 1)}).status_code == HTTPStatus.OK

    # 内容变了但版本没递增 -> 409, 提示下游递增版本。
    changed = _post(
        client,
        app.app_key,
        token,
        {"manifest": _manifest(app.app_key, 1, permission_name="查看全部订单")},
    )

    assert changed.status_code == HTTPStatus.CONFLICT


def test_manifest_sync_version_bump_applies_new_modules() -> None:
    app, token = _app_with_token("sync-bump")
    client = Client()
    assert _post(client, app.app_key, token, {"manifest": _manifest(app.app_key, 1)}).status_code == HTTPStatus.OK

    manifest = _manifest(app.app_key, 2)
    manifest["permissions"].append(
        {
            "key": "order.export",
            "name": "导出订单",
            "group_key": "order",
            "supported_scopes": ["SELF"],
        },
    )
    response = _post(client, app.app_key, token, {"manifest": manifest})

    assert response.status_code == HTTPStatus.OK
    assert response.json()["template_version"] == 2


def test_manifest_sync_rejects_wrong_app_key() -> None:
    app, token = _app_with_token("sync-owner")
    other, _ = _app_with_token("sync-other")

    response = _post(Client(), other.app_key, token, {"manifest": _manifest(other.app_key, 1)})

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not PermissionTemplateVersion.objects.filter(app=other).exists()


def test_manifest_sync_rejects_invalid_token() -> None:
    app, _token = _app_with_token("sync-badtoken")

    response = _post(Client(), app.app_key, "eat_invalid", {"manifest": _manifest(app.app_key, 1)})

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_manifest_sync_rejects_mismatched_manifest_app_key() -> None:
    app, token = _app_with_token("sync-mismatch")

    response = _post(Client(), app.app_key, token, {"manifest": _manifest("someone-else", 1)})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

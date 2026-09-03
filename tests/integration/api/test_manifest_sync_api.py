from __future__ import annotations

import json
from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    HANDOVER_CAPABILITY_UNDECLARED,
    App,
    PermissionTemplateVersion,
)
from easyauth.applications.services import AppCredentialService
from easyauth.audit.models import AuditLog
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db

_URL: Final = "/api/v1/apps/{app_key}/manifest-sync"
HTTPS_PORT: Final = 443
UPGRADED_MANIFEST_VERSION: Final = 2


def _app_with_token(app_key: str) -> tuple[App, str]:
    app = App.objects.create(app_key=app_key, name=app_key)
    issue = AppCredentialService.create_static_token(app=app, name="integration")
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


def test_manifest_sync_applies_new_version_and_autofills_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 已注册应用与静态 token。
    monkeypatch.setattr(
        "easyauth.config.net_policy.resolve_public_addresses",
        lambda _hostname, *, port, **_kwargs: (("93.184.216.34",) if port == HTTPS_PORT else ()),
    )
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
    initial = _post(client, app.app_key, token, {"manifest": _manifest(app.app_key, 1)})
    assert initial.status_code == HTTPStatus.OK

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
    initial = _post(client, app.app_key, token, {"manifest": _manifest(app.app_key, 1)})
    assert initial.status_code == HTTPStatus.OK

    manifest = _manifest(app.app_key, UPGRADED_MANIFEST_VERSION)
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
    assert response.json()["template_version"] == UPGRADED_MANIFEST_VERSION


def test_manifest_sync_clears_manifest_managed_lifecycle_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "easyauth.config.net_policy.resolve_public_addresses",
        lambda _hostname, *, port, **_kwargs: (("93.184.216.34",) if port == HTTPS_PORT else ()),
    )
    app, token = _app_with_token("sync-lifecycle-snapshot")
    client = Client()
    initial_manifest = _manifest(app.app_key, 1)
    initial_manifest["lifecycle"]["capabilities"] = ["handover.v2"]
    initial_manifest["lifecycle"]["handover_asset_types"] = [
        {
            "type": "order",
            "label": "订单",
            "detail_supported": False,
            "releasable": False,
        },
    ]
    assert (
        _post(
            client,
            app.app_key,
            token,
            {
                "manifest": initial_manifest,
                "base_url": "https://etrade.example.com",
            },
        ).status_code
        == HTTPStatus.OK
    )
    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED

    manifest_without_lifecycle = _manifest(app.app_key, UPGRADED_MANIFEST_VERSION)
    del manifest_without_lifecycle["lifecycle"]
    response = _post(
        client,
        app.app_key,
        token,
        {"manifest": manifest_without_lifecycle},
    )

    assert response.status_code == HTTPStatus.OK
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == ""
    assert config.onboard_url == ""
    assert config.updated_by == "manifest"
    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED


def test_manifest_sync_does_not_overwrite_console_owned_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "easyauth.config.net_policy.resolve_public_addresses",
        lambda _hostname, *, port, **_kwargs: (("93.184.216.34",) if port == HTTPS_PORT else ()),
    )
    app, token = _app_with_token("sync-console-owned")
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="https://admin.example.com/handover",
        enabled=False,
        updated_by="admin-1",
    )
    manifest = _manifest(app.app_key, 1)
    manifest["lifecycle"]["capabilities"] = ["handover.v2"]
    manifest["lifecycle"]["handover_asset_types"] = []

    response = _post(
        Client(),
        app.app_key,
        token,
        {"manifest": manifest, "base_url": "https://manifest.example.com"},
    )

    assert response.status_code == HTTPStatus.OK
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == "https://admin.example.com/handover"
    assert config.enabled is False
    assert config.updated_by == "admin-1"
    app.refresh_from_db()
    # 控制台已覆盖且未启用: handover_hook_url 读不到 URL, 能力必须跟存储口径走,
    # 不得因 manifest 相对路径 + base_url 被标成 declared。
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED


def test_conflicting_manifest_overrides_operational_none_to_undeclared() -> None:
    app, token = _app_with_token("sync-conflicting-none")
    app.handover_capability = HANDOVER_CAPABILITY_NONE
    app.handover_capability_declared_by = "admin-1"
    app.handover_capability_declared_at = timezone.now()
    app.save(
        update_fields=[
            "handover_capability",
            "handover_capability_declared_by",
            "handover_capability_declared_at",
            "updated_at",
        ],
    )
    manifest = _manifest(app.app_key, 1)
    manifest["lifecycle"]["capabilities"] = ["handover.v2", "handover.none"]
    manifest["lifecycle"]["handover_asset_types"] = []

    response = _post(Client(), app.app_key, token, {"manifest": manifest})

    assert response.status_code == HTTPStatus.OK
    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    audit = AuditLog.objects.get(event_type="handover_capability_conflict")
    assert audit.actor_type == "system"


def test_manifest_sync_rejects_wrong_app_key() -> None:
    _app, token = _app_with_token("sync-owner")
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


def test_manifest_sync_rejects_non_https_lifecycle_webhook_url() -> None:
    # Given: 已注册应用; lifecycle 带明文 http 本机 webhook(非 https 公网)。
    app, token = _app_with_token("sync-http-webhook")
    catalog_before = app.catalog_version
    manifest = _manifest(app.app_key, 1)
    manifest["lifecycle"]["handover_url"] = (
        "http://localhost:3001/api/v1/easyauth/lifecycle/handover"
    )

    # When: 推送该 manifest。
    response = _post(Client(), app.app_key, token, {"manifest": manifest})

    # Then: 结构化 422, 不落库任何模板/webhook 半成品。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    payload = response.json()
    assert payload["error"]["code"] == "SEMANTIC_VALIDATION_ERROR"
    assert (
        "https" in payload["error"]["message"].lower() or "Webhook" in payload["error"]["message"]
    )
    assert not PermissionTemplateVersion.objects.filter(app=app).exists()
    assert not AppWebhookConfig.objects.filter(app=app).exists()
    app.refresh_from_db()
    assert app.catalog_version == catalog_before

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.admin_console import auto_onboarding_api
from easyauth.applications.models import App, Permission, PermissionTemplateVersion

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

AUTO_ONBOARDING_URL: Final = "/console/api/v1/apps/auto-onboarding"
UPGRADED_SCHEMA_VERSION: Final = 2


def _manifest(schema_version: int = 1, *, permission_name: str = "查看演示对象") -> dict:
    return {
        "schema_version": schema_version,
        "app": {
            "app_key": "demoapp",
            "name": "Demo App",
            "description": "演示应用",
            "is_active": True,
        },
        "scopes": [
            {
                "key": "SELF",
                "name": "本人",
                "description": "",
                "is_active": True,
                "display_order": 10,
            },
        ],
        "permission_groups": [
            {
                "key": "demo",
                "name": "演示",
                "description": "",
                "parent_key": "",
                "display_order": 10,
                "is_active": True,
            },
            {
                "key": "demo.item",
                "name": "演示对象",
                "description": "",
                "parent_key": "demo",
                "display_order": 20,
                "is_active": True,
            },
        ],
        "permissions": [
            {
                "key": "demo.item.view",
                "name": permission_name,
                "name_en": "View Demo Item",
                "description": "",
                "group_key": "demo.item",
                "supported_scopes": ["SELF"],
                "risk_level": "standard",
                "is_active": True,
            },
        ],
        "authorization_groups": [
            {
                "key": "demo-viewer",
                "kind": "role",
                "name": "演示查看者",
                "description": "演示角色",
                "requestable": True,
                "is_active": True,
                "grants": [{"permission": "demo.item.view", "scope": "SELF", "is_active": True}],
            },
        ],
        "approval_rules": [
            {
                "target_type": "authorization_group",
                "target_key": "demo-viewer",
                "approver_userids": ["ak_admin"],
                "is_active": True,
            },
        ],
    }


def _descriptor(manifest: dict) -> dict:
    return {
        "descriptor_version": 1,
        "app": {
            "app_key": manifest["app"]["app_key"],
            "name": manifest["app"]["name"],
            "description": manifest["app"]["description"],
        },
        "manifest": manifest,
        "sdk": {"name": "easyauth-app-sdk-python", "version": "0.1.0"},
    }


def _patch_descriptor(monkeypatch: pytest.MonkeyPatch, descriptor: dict) -> None:
    monkeypatch.setattr(
        auto_onboarding_api,
        "_fetch_descriptor",
        lambda _base_url, _token: descriptor,
    )


def test_auto_onboarding_creates_app_and_imports_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("auto-onboard-admin")
    _patch_descriptor(monkeypatch, _descriptor(_manifest()))

    response = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "demoapp"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.OK, response.content
    payload = cast("dict[str, JsonValue]", response.json())
    assert payload["created"] is True
    assert payload["already_up_to_date"] is False
    assert payload["template_version"] == 1

    app = App.objects.get(app_key="demoapp")
    assert app.name == "Demo App"
    permission = Permission.objects.get(app=app, key="demo.item.view")
    # 权限双语显示名来自下游 manifest, 不允许 EasyAuth 硬编码。
    assert permission.name == "查看演示对象"
    assert permission.name_en == "View Demo Item"
    assert PermissionTemplateVersion.objects.filter(app=app, version=1).exists()


def test_auto_onboarding_is_idempotent_for_same_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("auto-onboard-idem-admin")
    _patch_descriptor(monkeypatch, _descriptor(_manifest()))

    first = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "demoapp"},
        content_type="application/json",
    )
    second = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "demoapp"},
        content_type="application/json",
    )

    assert first.status_code == HTTPStatus.OK
    assert second.status_code == HTTPStatus.OK
    second_payload = cast("dict[str, JsonValue]", second.json())
    assert second_payload["created"] is False
    assert second_payload["already_up_to_date"] is True
    assert PermissionTemplateVersion.objects.filter(app__app_key="demoapp").count() == 1


def test_auto_onboarding_rejects_same_version_different_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("auto-onboard-conflict-admin")
    _patch_descriptor(monkeypatch, _descriptor(_manifest()))
    first = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "demoapp"},
        content_type="application/json",
    )
    assert first.status_code == HTTPStatus.OK

    _patch_descriptor(
        monkeypatch,
        _descriptor(_manifest(permission_name="改名后的演示对象")),
    )
    conflict = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "demoapp"},
        content_type="application/json",
    )

    assert conflict.status_code == HTTPStatus.CONFLICT


def test_auto_onboarding_imports_new_version(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _logged_in_superuser("auto-onboard-upgrade-admin")
    _patch_descriptor(monkeypatch, _descriptor(_manifest()))
    assert (
        client.post(
            AUTO_ONBOARDING_URL,
            data={"base_url": "http://downstream.example", "app_key": "demoapp"},
            content_type="application/json",
        ).status_code
        == HTTPStatus.OK
    )

    _patch_descriptor(
        monkeypatch,
        _descriptor(
            _manifest(schema_version=UPGRADED_SCHEMA_VERSION, permission_name="改名后的演示对象"),
        ),
    )
    upgraded = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "demoapp"},
        content_type="application/json",
    )

    assert upgraded.status_code == HTTPStatus.OK
    payload = cast("dict[str, JsonValue]", upgraded.json())
    assert payload["template_version"] == UPGRADED_SCHEMA_VERSION
    permission = Permission.objects.get(app__app_key="demoapp", key="demo.item.view")
    assert permission.name == "改名后的演示对象"


def test_auto_onboarding_rejects_app_key_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _logged_in_superuser("auto-onboard-mismatch-admin")
    _patch_descriptor(monkeypatch, _descriptor(_manifest()))

    response = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "otherapp"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert not App.objects.filter(app_key="otherapp").exists()


def test_auto_onboarding_requires_superuser() -> None:
    _ = UserMirror.objects.create(authentik_user_id="auto-onboard-normal-user")
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = "auto-onboard-normal-user"
    session["easyauth_authentik_groups"] = ["Employees"]
    session.save()

    response = client.post(
        AUTO_ONBOARDING_URL,
        data={"base_url": "http://downstream.example", "app_key": "demoapp"},
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def _logged_in_superuser(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session["easyauth_authentik_groups"] = ["EasyAuth Admins"]
    session.save()
    return client

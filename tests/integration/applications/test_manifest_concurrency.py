from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import close_old_connections, connection
from django.test import RequestFactory

from easyauth.admin_console.webhook_config_api import _update_config
from easyauth.applications import manifest_import, permission_templates
from easyauth.applications.manifest_import import sync_app_manifest
from easyauth.applications.models import App
from easyauth.applications.ownership import ConsoleActor
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db(transaction=True)


def _manifest(app_key: str, version: int, *, handover_url: str = "") -> dict:
    payload = {
        "schema_version": version,
        "app": {"app_key": app_key, "name": "并发应用"},
        "scopes": [{"key": "SELF", "name": "本人"}],
        "permission_groups": [{"key": "core", "name": "核心"}],
        "permissions": [
            {
                "key": "core.read",
                "name": "查看",
                "group_key": "core",
                "supported_scopes": ["SELF"],
            },
        ],
        "authorization_groups": [],
        "approval_rules": [],
    }
    if handover_url:
        payload["lifecycle"] = {
            "handover_url": handover_url,
            "onboard_url": None,
            "capabilities": ["handover.v2"],
            "handover_asset_types": [],
        }
    return payload


def _require_postgresql() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("该并发锁语义仅在 PostgreSQL lane 验证。")


def test_concurrent_identical_same_version_imports_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_postgresql()
    app = App.objects.create(app_key="manifest-concurrent", name="并发导入")
    _ = sync_app_manifest(app=app, manifest=_manifest(app.app_key, 1), actor_id="seed")
    barrier = threading.Barrier(2)
    original_parse = manifest_import.parse_permission_template

    def synchronized_parse(*args: object, **kwargs: object):
        try:
            barrier.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(manifest_import, "parse_permission_template", synchronized_parse)

    def import_version() -> bool:
        close_old_connections()
        try:
            current = App.objects.get(pk=app.pk)
            return sync_app_manifest(
                app=current,
                manifest=_manifest(app.app_key, 2),
                actor_id="concurrent",
            ).already_up_to_date
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(import_version) for _ in range(2)]
        outcomes = sorted(future.result() for future in futures)

    assert outcomes == [False, True]


def test_console_webhook_update_wins_manifest_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_postgresql()
    app = App.objects.create(app_key="manifest-owner-race", name="归属竞态")
    _ = sync_app_manifest(app=app, manifest=_manifest(app.app_key, 1), actor_id="seed")
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="https://old.example/handover",
        updated_by="manifest",
    )
    manifest_read = threading.Event()
    release_manifest = threading.Event()
    console_done = threading.Event()

    def pause_manifest_validation(_url: str, **_kwargs: object) -> object:
        manifest_read.set()
        assert release_manifest.wait(timeout=3)
        return object()

    monkeypatch.setattr(
        permission_templates,
        "validate_public_https_url",
        pause_manifest_validation,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.webhook_config_api.validate_public_https_url",
        lambda _url, **_kwargs: object(),
    )

    def import_manifest() -> None:
        close_old_connections()
        try:
            sync_app_manifest(
                app=App.objects.get(pk=app.pk),
                manifest=_manifest(
                    app.app_key,
                    2,
                    handover_url="https://manifest.example/handover",
                ),
                actor_id="manifest",
            )
        finally:
            close_old_connections()

    def update_console() -> None:
        close_old_connections()
        try:
            request = RequestFactory().put(
                "/unused",
                data=json.dumps(
                    {
                        "enabled": False,
                        "handover_url": "https://admin.example/handover",
                        "approval_callback_url": "",
                        "onboard_url": "",
                    },
                ),
                content_type="application/json",
            )
            response = _update_config(
                request,
                App.objects.get(pk=app.pk),
                ConsoleActor(user_id="admin-race", is_superuser=True),
            )
            assert response.status_code == 200
            console_done.set()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        manifest_future = pool.submit(import_manifest)
        assert manifest_read.wait(timeout=3)
        console_future = pool.submit(update_console)
        _ = console_done.wait(timeout=0.5)
        release_manifest.set()
        manifest_future.result()
        console_future.result()

    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == "https://admin.example/handover"
    assert config.enabled is False
    assert config.updated_by == "admin-race"

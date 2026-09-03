from __future__ import annotations

import socket
from typing import Final

import pytest
from django.test import override_settings
from django.utils import timezone

from easyauth.applications.models import (
    HANDOVER_CAPABILITY_DECLARED,
    HANDOVER_CAPABILITY_NONE,
    HANDOVER_CAPABILITY_UNDECLARED,
    App,
)
from easyauth.applications.permission_template_lifecycle import sync_manifest_lifecycle
from easyauth.applications.permission_template_types import (
    AppManifestAppInput,
    AppManifestInput,
    AppManifestLifecycleInput,
    AppManifestPermissionGroupInput,
    AppManifestPermissionInput,
    AppManifestScopeInput,
)
from easyauth.config.net import BlockedHostError
from easyauth.lifecycle.handover_actions import initial_action_status_for_app
from easyauth.lifecycle.models import (
    ACTION_STATUS_BLOCKED,
    BLOCKED_REASON_CAPABILITY_UNDECLARED,
)
from easyauth.webhooks.models import AppWebhookConfig

pytestmark = pytest.mark.django_db

HTTPS_PORT: Final = 443
RELATIVE_HANDOVER_PATH: Final = "/api/v1/easyauth/lifecycle/handover"
PUBLIC_BASE_URL: Final = "https://etrade.example.com"
ABSOLUTE_HANDOVER_URL: Final = f"{PUBLIC_BASE_URL}{RELATIVE_HANDOVER_PATH}"
ADMIN_HANDOVER_URL: Final = "https://admin.example.com/handover"
TRUSTED_BASE_URL: Final = "https://etrade.jiefakj.com"
TRUSTED_HANDOVER_URL: Final = f"{TRUSTED_BASE_URL}{RELATIVE_HANDOVER_PATH}"
PRIVATE_ADDRESS: Final = "172.17.0.1"


def test_relative_handover_url_without_base_url_stays_undeclared() -> None:
    app = _app("life-rel-no-base")

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert not AppWebhookConfig.objects.filter(app=app).exists()
    status, blocked_reason, skip_reason, skipped_by = initial_action_status_for_app(app)
    assert status == ACTION_STATUS_BLOCKED
    assert blocked_reason == BLOCKED_REASON_CAPABILITY_UNDECLARED
    assert skip_reason == ""
    assert skipped_by == ""


def test_relative_handover_url_with_public_https_base_url_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app("life-rel-with-base")

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=PUBLIC_BASE_URL,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == ABSOLUTE_HANDOVER_URL
    assert config.enabled is True


def test_absolute_public_https_handover_url_is_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app("life-abs-https")

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=ABSOLUTE_HANDOVER_URL),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    assert AppWebhookConfig.objects.get(app=app).handover_url == ABSOLUTE_HANDOVER_URL


def test_console_overridden_webhook_url_drives_capability_when_usable() -> None:
    app = _app("life-console-usable")
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url=ADMIN_HANDOVER_URL,
        enabled=True,
        updated_by="admin-1",
    )

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == ADMIN_HANDOVER_URL
    assert config.updated_by == "admin-1"


def test_console_overridden_empty_webhook_url_keeps_capability_undeclared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app("life-console-empty")
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url="",
        enabled=True,
        updated_by="admin-1",
    )

    sync_manifest_lifecycle(
        app=app,
        template=_v2_template(app.app_key, handover_url=ABSOLUTE_HANDOVER_URL),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == ""
    assert config.updated_by == "admin-1"


def test_handover_none_on_undeclared_app_does_not_write_none() -> None:
    app = _app("life-none-fresh")

    sync_manifest_lifecycle(
        app=app,
        template=_none_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert app.handover_capability_declared_by == ""


def test_handover_none_does_not_depend_on_persisted_url() -> None:
    declared_at = timezone.now()
    app = App.objects.create(
        app_key="life-none-kept",
        name="life-none-kept",
        handover_capability=HANDOVER_CAPABILITY_NONE,
        handover_capability_declared_by="admin-1",
        handover_capability_declared_at=declared_at,
    )
    _ = AppWebhookConfig.objects.create(
        app=app,
        handover_url=ADMIN_HANDOVER_URL,
        enabled=True,
        updated_by="admin-1",
    )

    sync_manifest_lifecycle(
        app=app,
        template=_none_template(app.app_key, handover_url=RELATIVE_HANDOVER_PATH),
        downstream_base_url=None,
        actor_type="system",
    )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_NONE
    assert app.handover_capability_declared_by == "admin-1"
    assert app.handover_capability_declared_at == declared_at
    assert AppWebhookConfig.objects.get(app=app).handover_url == ADMIN_HANDOVER_URL


def test_private_dns_blocks_lifecycle_sync_when_allowlist_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dns(monkeypatch, PRIVATE_ADDRESS)
    app = _app("life-private-blocked")

    with (
        override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=()),
        pytest.raises(BlockedHostError),
    ):
        sync_manifest_lifecycle(
            app=app,
            template=_v2_template(app.app_key, handover_url=TRUSTED_HANDOVER_URL),
            downstream_base_url=None,
            actor_type="system",
        )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_UNDECLARED
    assert not AppWebhookConfig.objects.filter(app=app).exists()


def test_trusted_host_private_dns_declares_lifecycle_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_dns(monkeypatch, PRIVATE_ADDRESS)
    app = _app("life-trusted-private")

    with override_settings(EASYAUTH_TRUSTED_WEBHOOK_HOSTS=("etrade.jiefakj.com",)):
        sync_manifest_lifecycle(
            app=app,
            template=_v2_template(app.app_key, handover_url=TRUSTED_HANDOVER_URL),
            downstream_base_url=None,
            actor_type="system",
        )

    app.refresh_from_db()
    assert app.handover_capability == HANDOVER_CAPABILITY_DECLARED
    config = AppWebhookConfig.objects.get(app=app)
    assert config.handover_url == TRUSTED_HANDOVER_URL
    assert config.enabled is True


def _stub_dns(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    def fake_dns(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, HTTPS_PORT))]

    def fake_resolve(
        _hostname: str,
        *,
        port: int,
        timeout_seconds: float | None,
    ) -> tuple[tuple[object, ...], ...]:
        _ = timeout_seconds
        return ((socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port)),)

    monkeypatch.setattr(socket, "getaddrinfo", fake_dns)
    monkeypatch.setattr("easyauth.config.net_dns._resolve_addresses", fake_resolve)


def _allow_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "easyauth.config.net_policy.resolve_public_addresses",
        lambda _hostname, *, port, **_kwargs: (("93.184.216.34",) if port == HTTPS_PORT else ()),
    )


def _app(app_key: str) -> App:
    return App.objects.create(app_key=app_key, name=app_key)


def _v2_template(app_key: str, *, handover_url: str) -> AppManifestInput:
    return _template(
        app_key,
        lifecycle=AppManifestLifecycleInput(
            handover_url=handover_url,
            capabilities=("handover.v2",),
        ),
    )


def _none_template(app_key: str, *, handover_url: str) -> AppManifestInput:
    return _template(
        app_key,
        lifecycle=AppManifestLifecycleInput(
            handover_url=handover_url,
            capabilities=("handover.none",),
        ),
    )


def _template(app_key: str, *, lifecycle: AppManifestLifecycleInput) -> AppManifestInput:
    return AppManifestInput(
        schema_version=1,
        source="paste",
        imported_by="tester",
        raw_template="{}",
        app=AppManifestAppInput(app_key=app_key, name=app_key),
        scopes=(AppManifestScopeInput(key="SELF", name="本人"),),
        permission_groups=(AppManifestPermissionGroupInput(key="core", name="核心"),),
        permissions=(
            AppManifestPermissionInput(
                key="core.read",
                name="查看",
                group_key="core",
                supported_scopes=("SELF",),
            ),
        ),
        authorization_groups=(),
        approval_rules=(),
        lifecycle=lifecycle,
    )

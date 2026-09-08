from __future__ import annotations

from typing import Final

import pytest

from easyauth.applications.models import App
from easyauth.applications.permission_template_types import (
    AppManifestAppInput,
    AppManifestInput,
    AppManifestPermissionGroupInput,
    AppManifestPermissionInput,
    AppManifestScopeInput,
    AppManifestWebhookInput,
)
from easyauth.applications.permission_templates import apply_permission_template
from easyauth.webhooks.models import (
    WEBHOOK_EVENT_CATALOG_CHANGED,
    AppWebhookConfig,
    WebhookDelivery,
)

pytestmark = pytest.mark.django_db

HTTPS_PORT: Final = 443
SECRET: Final = "whsec_catalog_import"
EVENTS_PATH: Final = "/api/v1/easyauth/events"
HOST_A: Final = "app-a.example.com"
HOST_B: Final = "app-b.example.com"
URL_A: Final = f"https://{HOST_A}{EVENTS_PATH}"
URL_B: Final = f"https://{HOST_B}{EVENTS_PATH}"


def test_import_first_events_url_emits_catalog_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app_with_secret("imp-events-first")

    _ = apply_permission_template(app=app, template=_template(app.app_key, events_url=URL_B))

    deliveries = list(WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_CATALOG_CHANGED))
    assert len(deliveries) == 1
    assert deliveries[0].target_url == URL_B
    config = AppWebhookConfig.objects.get(app=app)
    assert config.events_url == URL_B
    assert HOST_B in config.allowed_hosts


def test_import_events_url_host_change_emits_to_new_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_https(monkeypatch)
    app = _app_with_secret("imp-events-change", events_url=URL_A)

    _ = apply_permission_template(app=app, template=_template(app.app_key, events_url=URL_B))

    deliveries = list(WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_CATALOG_CHANGED))
    assert len(deliveries) == 1
    assert deliveries[0].target_url == URL_B
    config = AppWebhookConfig.objects.get(app=app)
    assert config.events_url == URL_B
    assert HOST_A not in config.allowed_hosts
    assert HOST_B in config.allowed_hosts


def _allow_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "easyauth.config.net_policy.resolve_public_addresses",
        lambda _hostname, *, port, **_kwargs: (("93.184.216.34",) if port == HTTPS_PORT else ()),
    )


def _app_with_secret(app_key: str, *, events_url: str = "") -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret=SECRET,
        events_url=events_url,
        enabled=True,
        updated_by="manifest" if events_url else "",
    )
    return app


def _template(app_key: str, *, events_url: str) -> AppManifestInput:
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
        webhook=AppManifestWebhookInput(events_url=events_url),
    )

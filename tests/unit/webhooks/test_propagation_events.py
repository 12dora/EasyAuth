from __future__ import annotations

from typing import Final

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.catalog_version import bump_catalog_version
from easyauth.applications.models import App, AppScope, AuthorizationGroup
from easyauth.grants.query import resolve_user_permissions
from easyauth.grants.services import (
    AuthorizationGroupGrantInput,
    GrantMutationInput,
    GrantService,
)
from easyauth.webhooks.events import emit_catalog_changed, emit_grant_changed
from easyauth.webhooks.models import (
    WEBHOOK_EVENT_CATALOG_CHANGED,
    WEBHOOK_EVENT_GRANT_CHANGED,
    AppWebhookConfig,
    WebhookDelivery,
)

pytestmark = pytest.mark.django_db

SECRET: Final = "whsec_events"
EVENTS_URL: Final = "https://app.example.com/api/v1/easyauth/events"
SCOPE_KEY: Final = "GLOBAL"


def _app_with_events(app_key: str, *, events_url: str = EVENTS_URL, secret: str = SECRET) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret=secret,
        events_url=events_url,
        enabled=True,
    )
    return app


def _user(user_id: str) -> UserMirror:
    return UserMirror.objects.create(authentik_user_id=user_id, status="active")


def _group(app: App) -> AuthorizationGroup:
    _ = AppScope.objects.get_or_create(app=app, key=SCOPE_KEY, defaults={"name": "全局"})
    return AuthorizationGroup.objects.create(app=app, key="operator", kind="role", name="操作员")


def test_emit_grant_changed_persists_delivery_with_contract_payload() -> None:
    app = _app_with_events("evt-grant-app")
    user = _user("evt-grant-user")
    group = _group(app)
    grant = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            actor_type="admin",
            actor_id="admin-1",
        ),
    )
    snapshot = resolve_user_permissions(user=user, app=app)

    deliveries = list(WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_GRANT_CHANGED))
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.app_id == app.id
    assert delivery.target_url == EVENTS_URL
    assert delivery.payload["event_type"] == WEBHOOK_EVENT_GRANT_CHANGED
    assert delivery.payload["app_key"] == app.app_key
    assert delivery.payload["user_id"] == user.authentik_user_id
    assert delivery.payload["grant_version"] == grant.version
    assert delivery.payload["catalog_version"] == app.catalog_version
    assert delivery.payload["snapshot_version"] == snapshot.snapshot_version
    assert delivery.payload["changed_at"]


def test_emit_grant_changed_skips_without_events_url() -> None:
    app = App.objects.create(app_key="evt-grant-skip", name="skip")
    _ = AppWebhookConfig.objects.create(
        app=app,
        secret=SECRET,
        approval_callback_url="https://app.example.com/hook",
        enabled=True,
    )
    user = _user("evt-grant-skip-user")
    group = _group(app)

    _ = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            actor_type="admin",
            actor_id="admin-1",
        ),
    )

    assert not WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_GRANT_CHANGED).exists()


def test_emit_grant_changed_skips_without_secret() -> None:
    app = App.objects.create(app_key="evt-grant-nosecret", name="nosecret")
    _ = AppWebhookConfig.objects.create(app=app, events_url=EVENTS_URL, enabled=True)
    user = _user("evt-grant-nosecret-user")
    group = _group(app)
    grant = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=(AuthorizationGroupGrantInput(group, None),),
            actor_type="admin",
            actor_id="admin-1",
        ),
    )

    emit_grant_changed(grant)
    assert not WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_GRANT_CHANGED).exists()


def test_emit_catalog_changed_persists_delivery_with_contract_payload() -> None:
    app = _app_with_events("evt-catalog-app")

    bump_catalog_version(app, actor_id="admin-1", reason="permission import")

    deliveries = list(WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_CATALOG_CHANGED))
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.target_url == EVENTS_URL
    assert delivery.payload["event_type"] == WEBHOOK_EVENT_CATALOG_CHANGED
    assert delivery.payload["app_key"] == app.app_key
    assert delivery.payload["catalog_version"] == app.catalog_version
    assert isinstance(delivery.payload["changed_at"], str)
    assert delivery.payload["changed_at"]


def test_emit_catalog_changed_skips_without_config() -> None:
    app = App.objects.create(app_key="evt-catalog-skip", name="skip")
    emit_catalog_changed(app)
    bump_catalog_version(app, actor_id="admin-1", reason="noop")
    assert not WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_CATALOG_CHANGED).exists()

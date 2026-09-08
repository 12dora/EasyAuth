"""向下游推送授权快照失效事件: grant.changed / catalog.changed。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.grants.query import resolve_user_permissions
from easyauth.webhooks.delivery import WebhookNotConfiguredError, enqueue_delivery
from easyauth.webhooks.models import (
    WEBHOOK_EVENT_CATALOG_CHANGED,
    WEBHOOK_EVENT_GRANT_CHANGED,
    AppWebhookConfig,
)

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue
    from easyauth.grants.models import AccessGrant

logger = logging.getLogger(__name__)


def emit_grant_changed(grant: AccessGrant) -> None:
    """在授权事实所在事务内落投递行; 未配置 events_url 时跳过, 不回滚授权。"""
    app = grant.app
    if not _events_endpoint_configured(app):
        logger.info(
            "skip %s: webhook events_url not configured app_key=%s",
            WEBHOOK_EVENT_GRANT_CHANGED,
            app.app_key,
        )
        return
    app.refresh_from_db(fields=["app_key", "catalog_version"])
    snapshot = resolve_user_permissions(user=grant.user, app=app)
    payload: dict[str, JsonValue] = {
        "event_type": WEBHOOK_EVENT_GRANT_CHANGED,
        "app_key": app.app_key,
        "user_id": snapshot.user_id,
        "grant_version": snapshot.grant_version,
        "catalog_version": snapshot.catalog_version,
        "snapshot_version": snapshot.snapshot_version,
        "changed_at": timezone.now().isoformat(),
    }
    _enqueue_events_delivery(app=app, event_type=WEBHOOK_EVENT_GRANT_CHANGED, payload=payload)


def emit_catalog_changed(app: App) -> None:
    """目录版本提升后通知下游使该应用全部缓存快照失效。"""
    payload: dict[str, JsonValue] = {
        "event_type": WEBHOOK_EVENT_CATALOG_CHANGED,
        "app_key": app.app_key,
        "catalog_version": app.catalog_version,
        "changed_at": timezone.now().isoformat(),
    }
    _enqueue_events_delivery(app=app, event_type=WEBHOOK_EVENT_CATALOG_CHANGED, payload=payload)


def _events_endpoint_configured(app: App) -> bool:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    return config is not None and bool(config.secret) and bool(config.events_url)


def _enqueue_events_delivery(
    *,
    app: App,
    event_type: str,
    payload: dict[str, JsonValue],
) -> None:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    url = config.events_url if config is not None else ""
    try:
        _ = enqueue_delivery(app=app, event_type=event_type, url=url, payload=payload)
    except WebhookNotConfiguredError:
        logger.info(
            "skip %s: webhook events_url not configured app_key=%s",
            event_type,
            app.app_key,
        )

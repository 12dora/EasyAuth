from __future__ import annotations

import os

from celery import Celery
from celery.signals import task_success

from easyauth.config.runtime_health import (
    DIRECTORY_SYNC_SUCCESS,
    GRANT_CLEANUP_SUCCESS,
    NOTIFY_DELIVERY_SUCCESS,
    mark_heartbeat,
)

DJANGO_SETTINGS_MODULE = os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "easyauth.config.settings.base",
)

app = Celery("easyauth")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

_SUCCESS_HEARTBEATS = {
    "easyauth.authentik.sync_dingtalk_directory": DIRECTORY_SYNC_SUCCESS,
    "easyauth.grants.cleanup_expired_grants": GRANT_CLEANUP_SUCCESS,
    "easyauth.notify.deliver_message": NOTIFY_DELIVERY_SUCCESS,
}


@task_success.connect
def _record_critical_task_success(sender: object | None = None, **_kwargs: object) -> None:
    task_name = getattr(sender, "name", "")
    heartbeat = _SUCCESS_HEARTBEATS.get(task_name)
    if heartbeat is not None:
        mark_heartbeat(heartbeat)

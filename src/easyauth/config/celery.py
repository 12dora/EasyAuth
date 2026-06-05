from __future__ import annotations

import os

from celery import Celery

DJANGO_SETTINGS_MODULE = os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "easyauth.config.settings.base",
)

app = Celery("easyauth")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

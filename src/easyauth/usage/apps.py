from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class UsageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.usage"
    label = "usage"
    verbose_name = "用量监控"

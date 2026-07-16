from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class NotifyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.notify"
    verbose_name = "统一通知"

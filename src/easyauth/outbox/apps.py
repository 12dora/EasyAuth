from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class OutboxConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.outbox"
    verbose_name = "事务消息发件箱"

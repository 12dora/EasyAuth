from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class PortalConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.portal"
    verbose_name = "Portal"

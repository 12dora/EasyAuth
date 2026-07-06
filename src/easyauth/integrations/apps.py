from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.integrations"
    verbose_name = "Integrations"

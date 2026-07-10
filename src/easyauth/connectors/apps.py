from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class ConnectorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.connectors"
    verbose_name = "Provisioning Connectors"

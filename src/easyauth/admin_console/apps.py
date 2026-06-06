from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class AdminConsoleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.admin_console"
    verbose_name = "Admin Console"

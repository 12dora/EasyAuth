from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class ApplicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.applications"
    verbose_name = "Applications"

from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class TeamsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.teams"
    verbose_name = "Teams"

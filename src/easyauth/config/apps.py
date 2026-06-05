from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class EasyAuthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    label = "easyauth_config"
    name = "easyauth.config"
    verbose_name = "EasyAuth"

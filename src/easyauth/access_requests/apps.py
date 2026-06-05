from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class AccessRequestsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.access_requests"
    verbose_name = "Access Requests"

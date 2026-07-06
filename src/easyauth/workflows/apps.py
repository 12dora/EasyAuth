from __future__ import annotations

from typing import final

from django.apps import AppConfig


@final
class WorkflowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easyauth.workflows"
    verbose_name = "Workflows"

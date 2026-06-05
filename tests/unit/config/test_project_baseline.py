from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import django
from django.urls import reverse

from easyauth.config.settings import test as project_settings


def test_django_project_baseline_is_loadable() -> None:
    # Given
    if "DJANGO_SETTINGS_MODULE" not in os.environ:
        os.environ["DJANGO_SETTINGS_MODULE"] = "easyauth.config.settings.test"

    # When
    django.setup()

    # Then
    assert project_settings.ROOT_URLCONF == "easyauth.config.urls"
    assert project_settings.CELERY_TASK_ALWAYS_EAGER is True
    assert "rest_framework" in project_settings.INSTALLED_APPS
    assert "oauth2_provider" in project_settings.INSTALLED_APPS
    assert reverse("health") == "/health/"


def test_manage_check_succeeds() -> None:
    # Given
    repo_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "easyauth.config.settings.test"

    # When
    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Then
    assert result.returncode == 0, result.stderr
    assert "System check identified no issues" in result.stdout

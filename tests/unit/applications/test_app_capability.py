from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from easyauth.applications.capabilities import app_capability_config, app_capability_enabled
from easyauth.applications.models import (
    CAPABILITY_DIRECTORY,
    CAPABILITY_NOTIFY,
    App,
    AppCapability,
)

pytestmark = pytest.mark.django_db


def test_app_capability_unique_per_app_and_capability() -> None:
    app = App.objects.create(app_key="cap-unique", name="Cap Unique")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_DIRECTORY,
        enabled=True,
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        _ = AppCapability.objects.create(
            app=app,
            capability=CAPABILITY_DIRECTORY,
            enabled=False,
        )


def test_app_capability_enabled_defaults_to_false_without_row() -> None:
    app = App.objects.create(app_key="cap-default", name="Cap Default")

    assert app_capability_enabled(app.id, CAPABILITY_DIRECTORY) is False
    assert app_capability_enabled(app.id, CAPABILITY_NOTIFY) is False
    assert app_capability_config(app.id, CAPABILITY_NOTIFY) == {}


def test_app_capability_enabled_respects_enabled_flag() -> None:
    app = App.objects.create(app_key="cap-flag", name="Cap Flag")
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_DIRECTORY,
        enabled=False,
    )
    _ = AppCapability.objects.create(
        app=app,
        capability=CAPABILITY_NOTIFY,
        enabled=True,
        config={"daily_recipient_quota": 1000, "rate_per_minute": 30},
    )

    assert app_capability_enabled(app.id, CAPABILITY_DIRECTORY) is False
    assert app_capability_enabled(app.id, CAPABILITY_NOTIFY) is True
    assert app_capability_config(app.id, CAPABILITY_NOTIFY) == {
        "daily_recipient_quota": 1000,
        "rate_per_minute": 30,
    }
    assert app_capability_config(app.id, CAPABILITY_DIRECTORY) == {}


def test_same_capability_can_exist_on_different_apps() -> None:
    first = App.objects.create(app_key="cap-a", name="A")
    second = App.objects.create(app_key="cap-b", name="B")
    _ = AppCapability.objects.create(app=first, capability=CAPABILITY_NOTIFY, enabled=True)
    _ = AppCapability.objects.create(app=second, capability=CAPABILITY_NOTIFY, enabled=True)

    assert app_capability_enabled(first.id, CAPABILITY_NOTIFY) is True
    assert app_capability_enabled(second.id, CAPABILITY_NOTIFY) is True

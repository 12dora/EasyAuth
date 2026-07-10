from __future__ import annotations

import pytest
from django.conf import settings

from easyauth.outbox.services import DispatchResult
from easyauth.tasks import outbox as outbox_task_module
from easyauth.tasks.outbox import dispatch_outbox_task

pytestmark = pytest.mark.django_db


def test_dispatch_task_returns_scan_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        outbox_task_module,
        "dispatch_pending_events",
        lambda: DispatchResult(claimed=3, published=2, failed=1),
    )

    result = dispatch_outbox_task()

    assert result == {"claimed": 3, "published": 2, "failed": 1}


def test_outbox_dispatcher_is_registered_for_periodic_scan() -> None:
    schedule = settings.CELERY_BEAT_SCHEDULE["outbox-dispatch"]

    assert schedule["task"] == "easyauth.outbox.dispatch_pending"
    assert schedule["schedule"] > 0
    assert "easyauth.tasks.outbox" in settings.CELERY_IMPORTS

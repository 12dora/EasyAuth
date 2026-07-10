from __future__ import annotations

import pytest

from easyauth.applications.models import App
from easyauth.connectors.dispatch import RECONCILE_TASK_NAME, request_instance_reconcile
from easyauth.connectors.models import SYNC_TRIGGER_EVENT, ConnectorInstance
from easyauth.outbox.models import OutboxEvent

pytestmark = pytest.mark.django_db


def test_connector_generation_and_outbox_event_commit_together() -> None:
    app = App.objects.create(app_key="outbox-connector", name="Outbox connector")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)

    queued = request_instance_reconcile(instance.id, trigger=SYNC_TRIGGER_EVENT)

    instance.refresh_from_db()
    assert queued is True
    event = OutboxEvent.objects.get(
        event_key=f"connector-reconcile:{instance.id}:{instance.reconcile_generation}",
    )
    assert event.task_name == RECONCILE_TASK_NAME
    assert event.args == [instance.id]

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, cast
from uuid import uuid4

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from easyauth.applications.models import App, AppNotificationChannel

pytestmark = pytest.mark.django_db(transaction=True)

if TYPE_CHECKING:
    from collections.abc import Iterator

_NOTIFY_0007 = "0007_remove_legacy_recipient_identity"
_NOTIFY_0008 = "0008_oa_message_fields"
_NOTIFY_0009 = "0009_remove_notifymessage_deeplink_title"
_NOTIFY_0010 = "0010_notifyrecipient_robot_delivery"
_OA_COLUMNS = {"form_fields", "app_display_name", "author"}
_ROBOT_COLUMNS = {"robot_process_query_key", "robot_status", "robot_error"}


class _MessageRow(Protocol):
    template: str


class _MessageManager(Protocol):
    def create(self, **kwargs: object) -> object: ...
    def get(self, **kwargs: object) -> _MessageRow: ...


class _MessageModel(Protocol):
    objects: ClassVar[_MessageManager]


@pytest.fixture(autouse=True)
def restore_latest_migrations() -> Iterator[None]:
    try:
        yield
    finally:
        _restore_latest()


def test_oa_message_fields_migration_rewrites_and_reverses() -> None:
    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0007))
    table = "notify_notifymessage"
    assert _column_names(table).isdisjoint(_OA_COLUMNS)

    app_id, channel_id = _seed_app_and_channel()
    historical = _historical_message_model(_NOTIFY_0007)
    message_id = uuid4()
    _ = historical.objects.create(
        id=message_id,
        app_id=app_id,
        channel_id=channel_id,
        template="markdown",
        content="旧正文",
        payload_hash="a" * 64,
        requested_credential_type="static_token",
        requested_credential_id=1,
    )

    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0008))
    assert _OA_COLUMNS.issubset(_column_names(table))
    oa_model = _historical_message_model(_NOTIFY_0008)
    assert oa_model.objects.get(id=message_id).template == "oa"

    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0007))
    restored = _historical_message_model(_NOTIFY_0007)
    assert restored.objects.get(id=message_id).template == "markdown"
    assert _column_names(table).isdisjoint(_OA_COLUMNS)


def test_deeplink_title_column_removed_and_reversible() -> None:
    table = "notify_notifymessage"
    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0008))
    assert "deeplink_title" in _column_names(table)

    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0009))
    assert "deeplink_title" not in _column_names(table)

    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0008))
    assert "deeplink_title" in _column_names(table)


def test_robot_delivery_columns_added_and_reversible() -> None:
    table = "notify_notifyrecipient"
    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0009))
    assert _column_names(table).isdisjoint(_ROBOT_COLUMNS)

    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0010))
    assert _ROBOT_COLUMNS.issubset(_column_names(table))

    _ = MigrationExecutor(connection).migrate(_targets_with_notify(_NOTIFY_0009))
    assert _column_names(table).isdisjoint(_ROBOT_COLUMNS)


def _targets_with_notify(migration: str) -> list[tuple[str, str]]:
    executor = MigrationExecutor(connection)
    return [
        ("notify", migration) if app == "notify" else (app, node)
        for app, node in executor.loader.graph.leaf_nodes()
    ]


def _restore_latest() -> None:
    executor = MigrationExecutor(connection)
    _ = executor.migrate(executor.loader.graph.leaf_nodes())


def _column_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table)
    return {cast("str", column.name) for column in description}


def _historical_message_model(migration: str) -> _MessageModel:
    executor = MigrationExecutor(connection)
    apps = executor.loader.project_state(_targets_with_notify(migration)).apps
    return cast("_MessageModel", apps.get_model("notify", "NotifyMessage"))


def _seed_app_and_channel() -> tuple[int, int]:
    app = App.objects.create(app_key="notify-oa-mig", name="迁移应用")
    channel = AppNotificationChannel.objects.create(
        app=app,
        name="迁移通道",
        dingtalk_app_key="mig-key",
        dingtalk_app_secret="mig-secret",
        agent_id="1001",
        directory_source_slug="dingtalk",
        corp_id="corp-mig",
        version=1,
        is_active=True,
        created_by="pytest",
    )
    return app.id, channel.id

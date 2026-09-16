from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

if TYPE_CHECKING:
    from collections.abc import Iterator

_BEFORE = [("applications", "0034_backfill_builtin_super_admin")]
_AFTER = [("applications", "0035_integrationsettings_dingtalk_notify_credentials")]
_NOTIFY_COLUMNS = {
    "dingtalk_notify_app_key",
    "dingtalk_notify_app_secret",
    "dingtalk_notify_agent_id",
}


@pytest.fixture(autouse=True)
def restore_latest_migrations() -> Iterator[None]:
    try:
        yield
    finally:
        executor = MigrationExecutor(connection)
        _ = executor.migrate(executor.loader.graph.leaf_nodes())


def test_dingtalk_notify_credential_migration_adds_blank_columns() -> None:
    _ = MigrationExecutor(connection).migrate(_BEFORE)
    table = "applications_integrationsettings"
    assert _column_names(table).isdisjoint(_NOTIFY_COLUMNS)

    _ = MigrationExecutor(connection).migrate(_AFTER)
    assert _NOTIFY_COLUMNS.issubset(_column_names(table))

    _ = MigrationExecutor(connection).migrate(_BEFORE)
    assert _column_names(table).isdisjoint(_NOTIFY_COLUMNS)


def test_notify_head_bgcolor_migration_reversible() -> None:
    color_after = [("applications", "0036_app_notify_head_bgcolor")]
    table = "applications_app"
    _ = MigrationExecutor(connection).migrate(_AFTER)
    assert "notify_head_bgcolor" not in _column_names(table)

    _ = MigrationExecutor(connection).migrate(color_after)
    assert "notify_head_bgcolor" in _column_names(table)

    _ = MigrationExecutor(connection).migrate(_AFTER)
    assert "notify_head_bgcolor" not in _column_names(table)


def test_notify_robot_enabled_migration_adds_true_default() -> None:
    before = [("applications", "0036_app_notify_head_bgcolor")]
    after = [("applications", "0037_integrationsettings_dingtalk_notify_robot_enabled")]
    table = "applications_integrationsettings"
    _ = MigrationExecutor(connection).migrate(before)
    assert "dingtalk_notify_robot_enabled" not in _column_names(table)

    _ = MigrationExecutor(connection).migrate(after)
    assert "dingtalk_notify_robot_enabled" in _column_names(table)

    _ = MigrationExecutor(connection).migrate(before)
    assert "dingtalk_notify_robot_enabled" not in _column_names(table)


def _column_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table)
    return {cast("str", column.name) for column in description}

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, cast

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

if TYPE_CHECKING:
    from collections.abc import Iterator

_BEFORE = "0020_usermirror_avatar_url_textfield"
_AFTER = "0021_dingtalkusermirror_name_pinyin"
_PINYIN_COLUMNS = {"name_pinyin", "name_pinyin_initials"}


class _DingTalkUserRow(Protocol):
    pk: int
    name_pinyin: str
    name_pinyin_initials: str


class _DingTalkUserManager(Protocol):
    def create(self, **kwargs: object) -> _DingTalkUserRow: ...

    def get(self, **kwargs: object) -> _DingTalkUserRow: ...


class _DingTalkUserModel(Protocol):
    objects: ClassVar[_DingTalkUserManager]


@pytest.fixture(autouse=True)
def restore_latest_migrations() -> Iterator[None]:
    try:
        yield
    finally:
        _restore_latest()


def test_dingtalk_user_pinyin_migration_backfills_existing_names() -> None:
    table = "accounts_dingtalkusermirror"
    _ = MigrationExecutor(connection).migrate(_targets_with_accounts(_BEFORE))
    assert _column_names(table).isdisjoint(_PINYIN_COLUMNS)

    historical = _historical_dingtalk_user(_BEFORE)
    row = historical.objects.create(
        source_slug="dingtalk",
        corp_id="corp-mig-pinyin",
        user_id="user-mig-pinyin",
        name="张甜",
    )

    _ = MigrationExecutor(connection).migrate(_targets_with_accounts(_AFTER))
    assert _PINYIN_COLUMNS.issubset(_column_names(table))
    filled = _historical_dingtalk_user(_AFTER).objects.get(pk=row.pk)
    assert filled.name_pinyin == "zhangtian"
    assert filled.name_pinyin_initials == "zt"

    _ = MigrationExecutor(connection).migrate(_targets_with_accounts(_BEFORE))
    assert _column_names(table).isdisjoint(_PINYIN_COLUMNS)


def _targets_with_accounts(migration: str) -> list[tuple[str, str]]:
    executor = MigrationExecutor(connection)
    return [
        ("accounts", migration) if app == "accounts" else (app, node)
        for app, node in executor.loader.graph.leaf_nodes()
    ]


def _restore_latest() -> None:
    executor = MigrationExecutor(connection)
    _ = executor.migrate(executor.loader.graph.leaf_nodes())


def _column_names(table: str) -> set[str]:
    with connection.cursor() as cursor:
        description = connection.introspection.get_table_description(cursor, table)
    return {cast("str", column.name) for column in description}


def _historical_dingtalk_user(migration: str) -> _DingTalkUserModel:
    executor = MigrationExecutor(connection)
    apps = executor.loader.project_state(_targets_with_accounts(migration)).apps
    return cast("_DingTalkUserModel", apps.get_model("accounts", "DingTalkUserMirror"))

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

if TYPE_CHECKING:
    from collections.abc import Iterator

_BEFORE_TARGETS = [
    ("applications", "0029_managed_scope_policy_relationship_triggers"),
    ("accounts", "0015_alter_usermirror_options_and_more"),
    ("access_requests", "0012_accessrequest_base_grant_and_more"),
]
_AFTER_TARGETS = [
    ("applications", "0029_managed_scope_policy_relationship_triggers"),
    ("accounts", "0015_alter_usermirror_options_and_more"),
    ("access_requests", "0014_access_request_relationship_triggers"),
]


class _CreatedModel(Protocol):
    id: int


class _DeleteQuerySet(Protocol):
    def delete(self) -> tuple[int, dict[str, int]]: ...


class _CreateManager(Protocol):
    def create(self, **kwargs: object) -> _CreatedModel: ...


class _RequestManager(_CreateManager, Protocol):
    def filter(self, **kwargs: object) -> _DeleteQuerySet: ...


class _CreateOnlyModel(Protocol):
    objects: _CreateManager


class _RequestModel(Protocol):
    objects: _RequestManager


@pytest.fixture(autouse=True)
def restore_latest_access_request_migrations() -> Iterator[None]:
    try:
        yield
    finally:
        executor = MigrationExecutor(connection)
        _ = executor.migrate(_AFTER_TARGETS)


def test_group_grant_snapshot_migration_blocks_unfinished_group_requests() -> None:
    before = _migrate(_BEFORE_TARGETS)
    _seed_unfinished_group_request(before)

    executor = MigrationExecutor(connection)
    with pytest.raises(RuntimeError, match="未完成或可重试的授权组申请"):
        _ = executor.migrate(_AFTER_TARGETS)

    failed = MigrationExecutor(connection)
    _delete_legacy_access_requests(failed)


def _migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    _ = executor.migrate(targets)
    return MigrationExecutor(connection)


def _seed_unfinished_group_request(executor: MigrationExecutor) -> None:
    apps = executor.loader.project_state(_BEFORE_TARGETS).apps
    app_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "App")),
    )
    user_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("accounts", "UserMirror")),
    )
    group_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "AuthorizationGroup")),
    )
    request_model = cast(
        "type[_RequestModel]",
        cast("object", apps.get_model("access_requests", "AccessRequest")),
    )
    request_group_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("access_requests", "AccessRequestGroup")),
    )
    app = app_model.objects.create(app_key="snapshot-migration-app", name="Snapshot Migration")
    user = user_model.objects.create(authentik_user_id="snapshot-migration-user")
    group = group_model.objects.create(app_id=app.id, key="reader", kind="role", name="Reader")
    access_request = request_model.objects.create(
        user_id=user.id,
        app_id=app.id,
        status="submitted",
        idempotency_key="snapshot-migration-request",
        payload_digest="a" * 64,
        reason="历史未完成授权组申请",
    )
    _created_group_link = request_group_model.objects.create(
        access_request_id=access_request.id,
        authorization_group_id=group.id,
    )


def _delete_legacy_access_requests(executor: MigrationExecutor) -> None:
    apps = executor.loader.project_state(_BEFORE_TARGETS).apps
    request_model = cast(
        "type[_RequestModel]",
        cast("object", apps.get_model("access_requests", "AccessRequest")),
    )
    _ = request_model.objects.filter(idempotency_key="snapshot-migration-request").delete()

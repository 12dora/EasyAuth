from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Protocol, Self, cast

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import override_settings
from django.utils import timezone

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID


class _HistoricalQuery(Protocol):
    def __iter__(self) -> Iterator[object]: ...
    def values_list(self, *fields: str, flat: bool = False) -> Self: ...
    def delete(self) -> tuple[int, dict[str, int]]: ...
    def exists(self) -> bool: ...


class _AppRow(Protocol):
    id: int


class _MessageRow(Protocol):
    id: UUID
    channel_id: int


class _ChannelRow(Protocol):
    id: int
    dingtalk_app_key: str
    dingtalk_app_secret: str
    agent_id: str
    directory_source_slug: str
    corp_id: str
    created_by: str


class _RecipientRow(Protocol):
    status: str


class _AppManager(Protocol):
    def create(self, **kwargs: object) -> _AppRow: ...


class _AppModel(Protocol):
    objects: ClassVar[_AppManager]


class _CreateOnlyManager(Protocol):
    def create(self, **kwargs: object) -> object: ...
    def filter(self, **kwargs: object) -> _HistoricalQuery: ...


class _CreateOnlyModel(Protocol):
    objects: ClassVar[_CreateOnlyManager]


class _MessageManager(Protocol):
    def create(self, **kwargs: object) -> _MessageRow: ...
    def get(self, **kwargs: object) -> _MessageRow: ...
    def filter(self, **kwargs: object) -> _HistoricalQuery: ...
    def all(self) -> _HistoricalQuery: ...


class _MessageModel(Protocol):
    objects: ClassVar[_MessageManager]


class _ChannelManager(Protocol):
    def get(self, **kwargs: object) -> _ChannelRow: ...
    def filter(self, **kwargs: object) -> _HistoricalQuery: ...


class _ChannelModel(Protocol):
    objects: ClassVar[_ChannelManager]


class _RecipientManager(Protocol):
    def create(self, **kwargs: object) -> _RecipientRow: ...
    def get(self, **kwargs: object) -> _RecipientRow: ...


class _RecipientModel(Protocol):
    objects: ClassVar[_RecipientManager]


pytestmark = pytest.mark.django_db(transaction=True)

_BEFORE_TARGETS = [
    ("accounts", "0013_directory_user_contact_tombstones"),
    ("applications", "0025_credential_capabilities"),
    ("notify", "0002_notifymessage_deeplink_title"),
]
_AT_0026_TARGETS = [
    ("applications", "0026_app_notification_channel"),
    ("notify", "0002_notifymessage_deeplink_title"),
]
_AFTER_TARGETS = [
    ("applications", "0027_notification_channel_directory_scope"),
    ("notify", "0004_notify_recipient_reconcile_cursor"),
]


def _migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    _ = executor.migrate(targets)
    return MigrationExecutor(connection)


@pytest.fixture(autouse=True)
def restore_latest_migrations() -> Iterator[None]:
    try:
        yield
    finally:
        executor = MigrationExecutor(connection)
        _ = executor.migrate(_AFTER_TARGETS)


def _seed_legacy_message(
    executor: MigrationExecutor,
    *,
    app_key: str,
    status: str = "pending",
    capability_enabled: bool = True,
) -> tuple[int, str]:
    apps = executor.loader.project_state(_BEFORE_TARGETS).apps
    app_model = cast(
        "type[_AppModel]",
        cast("object", apps.get_model("applications", "App")),
    )
    capability_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "AppCapability")),
    )
    message_model = cast(
        "type[_MessageModel]",
        cast("object", apps.get_model("notify", "NotifyMessage")),
    )
    app = app_model.objects.create(app_key=app_key, name=app_key)
    _ = capability_model.objects.create(
        app_id=app.id,
        capability="notify",
        enabled=capability_enabled,
    )
    message = message_model.objects.create(
        app_id=app.id,
        template="text",
        content="legacy",
        payload_hash="a" * 64,
        status=status,
        requested_credential_type="static_token",
        requested_credential_id=1,
    )
    return app.id, str(message.id)


def _seed_directory_scope(
    executor: MigrationExecutor,
    *,
    source_slug: str = "dingtalk",
    corp_id: str = "migration-corp",
) -> None:
    apps = executor.loader.project_state(_BEFORE_TARGETS).apps
    sync_state_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("accounts", "DingTalkDirectorySyncState")),
    )
    _ = sync_state_model.objects.create(
        source_slug=source_slug,
        corp_id=corp_id,
        status="success",
    )


def _seed_mirror_only_scope(
    executor: MigrationExecutor,
    *,
    model_name: str,
    source_slug: str = "dingtalk",
    corp_id: str = "mirror-only-corp",
) -> None:
    apps = executor.loader.project_state(_BEFORE_TARGETS).apps
    mirror_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("accounts", model_name)),
    )
    common: dict[str, object] = {
        "source_slug": source_slug,
        "corp_id": corp_id,
    }
    if model_name == "DingTalkUserMirror":
        common.update(user_id="mirror-user", status="active")
    else:
        common.update(dept_id="mirror-dept", name="Mirror Department")
    _ = mirror_model.objects.create(**common)


def test_migrations_copy_db_override_and_backfill_existing_message() -> None:
    before = _migrate(_BEFORE_TARGETS)
    _seed_directory_scope(before)
    app_id, message_id = _seed_legacy_message(before, app_key="migration-db-channel")
    apps = before.loader.project_state(_BEFORE_TARGETS).apps
    integration_settings = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "IntegrationSettings")),
    )
    _ = integration_settings.objects.create(
        id=1,
        dingtalk_app_key="db-key",
        dingtalk_app_secret="db-secret",  # noqa: S106
        dingtalk_agent_id="1001",
    )

    with override_settings(
        EASYAUTH_DINGTALK_APP_KEY="env-key",
        EASYAUTH_DINGTALK_APP_SECRET="env-secret",  # noqa: S106
        EASYAUTH_DINGTALK_AGENT_ID="2002",
    ):
        after = _migrate(_AFTER_TARGETS)

    migrated_apps = after.loader.project_state(_AFTER_TARGETS).apps
    channel_model = cast(
        "type[_ChannelModel]",
        cast("object", migrated_apps.get_model("applications", "AppNotificationChannel")),
    )
    message_model = cast(
        "type[_MessageModel]",
        cast("object", migrated_apps.get_model("notify", "NotifyMessage")),
    )
    channel = channel_model.objects.get(app_id=app_id, is_active=True)
    message = message_model.objects.get(id=message_id)
    assert channel.dingtalk_app_key == "db-key"
    assert channel.dingtalk_app_secret == "db-secret"  # noqa: S105
    assert channel.agent_id == "1001"
    assert channel.directory_source_slug == "dingtalk"
    assert channel.corp_id == "migration-corp"
    assert message.channel_id == channel.id

    reversed_executor = _migrate(_BEFORE_TARGETS)
    reversed_apps = reversed_executor.loader.project_state(_BEFORE_TARGETS).apps
    reversed_message_model = cast(
        "type[_MessageModel]",
        cast("object", reversed_apps.get_model("notify", "NotifyMessage")),
    )
    assert reversed_message_model.objects.get(id=message_id).id == message.id
    _ = _migrate(_AFTER_TARGETS)


def test_migrations_use_environment_fallback_for_all_legacy_messages() -> None:
    before = _migrate(_BEFORE_TARGETS)
    _seed_directory_scope(before)
    app_id, pending_id = _seed_legacy_message(
        before,
        app_key="migration-env-channel",
        capability_enabled=False,
    )
    apps = before.loader.project_state(_BEFORE_TARGETS).apps
    message_model = cast(
        "type[_MessageModel]",
        cast("object", apps.get_model("notify", "NotifyMessage")),
    )
    sending = message_model.objects.create(
        app_id=app_id,
        template="text",
        content="legacy-sending",
        payload_hash="b" * 64,
        status="sending",
        requested_credential_type="static_token",
        requested_credential_id=2,
    )
    recipient_model = cast(
        "type[_RecipientModel]",
        cast("object", apps.get_model("notify", "NotifyRecipient")),
    )
    _ = recipient_model.objects.create(
        message_id=sending.id,
        raw_ref="dt:legacy-user",
        dingtalk_userid="legacy-user",
        status="sent",
        dingtalk_task_id="legacy-task",
        sent_at=timezone.now(),
    )

    with override_settings(
        EASYAUTH_DINGTALK_APP_KEY="env-key",
        EASYAUTH_DINGTALK_APP_SECRET="env-secret",  # noqa: S106
        EASYAUTH_DINGTALK_AGENT_ID="3003",
    ):
        after = _migrate(_AFTER_TARGETS)

    migrated_apps = after.loader.project_state(_AFTER_TARGETS).apps
    channel_model = cast(
        "type[_ChannelModel]",
        cast("object", migrated_apps.get_model("applications", "AppNotificationChannel")),
    )
    migrated_message_model = cast(
        "type[_MessageModel]",
        cast("object", migrated_apps.get_model("notify", "NotifyMessage")),
    )
    migrated_recipient_model = cast(
        "type[_RecipientModel]",
        cast("object", migrated_apps.get_model("notify", "NotifyRecipient")),
    )
    channel = channel_model.objects.get(app_id=app_id, is_active=True)
    channel_ids = set(
        migrated_message_model.objects.filter(id__in=[pending_id, sending.id]).values_list(
            "channel_id",
            flat=True,
        ),
    )
    assert channel.dingtalk_app_key == "env-key"
    assert channel.dingtalk_app_secret == "env-secret"  # noqa: S105
    assert channel.agent_id == "3003"
    assert channel.created_by == "migration-notify-history"
    assert channel.directory_source_slug == "dingtalk"
    assert channel.corp_id == "migration-corp"
    assert channel_ids == {channel.id}
    assert migrated_recipient_model.objects.get(message_id=sending.id).status == "sent"
    with pytest.raises(IntegrityError), transaction.atomic():
        _ = migrated_message_model.objects.create(
            app_id=app_id,
            template="text",
            content="must-have-channel",
            payload_hash="c" * 64,
            status="pending",
            requested_credential_type="static_token",
            requested_credential_id=3,
        )


def test_message_backfill_blocks_safely_when_no_complete_channel_exists() -> None:
    before = _migrate(_BEFORE_TARGETS)
    _seed_directory_scope(before)
    _app_id, _message_id = _seed_legacy_message(before, app_key="migration-missing-channel")
    secret_marker = "migration-secret-must-not-leak"  # noqa: S105

    with override_settings(
        EASYAUTH_DINGTALK_APP_KEY="env-key",
        EASYAUTH_DINGTALK_APP_SECRET=secret_marker,
        EASYAUTH_DINGTALK_AGENT_ID="",
    ):
        executor = MigrationExecutor(connection)
        with pytest.raises(RuntimeError) as captured:
            _ = executor.migrate(_AFTER_TARGETS)

    assert "migration-missing-channel" in str(captured.value)
    assert secret_marker not in str(captured.value)

    # 失败迁移应阻断; 清除测试遗留消息后才能在 fixture 收尾时恢复最新 schema。
    failed_executor = MigrationExecutor(connection)
    failed_apps = failed_executor.loader.project_state(_BEFORE_TARGETS).apps
    failed_message_model = cast(
        "type[_MessageModel]",
        cast("object", failed_apps.get_model("notify", "NotifyMessage")),
    )
    _ = failed_message_model.objects.all().delete()


def test_history_channel_inference_fails_safely_without_directory_scope() -> None:
    before = _migrate(_BEFORE_TARGETS)
    _app_id, _message_id = _seed_legacy_message(
        before,
        app_key="migration-history-zero-scope",
        capability_enabled=False,
    )

    with override_settings(
        EASYAUTH_DINGTALK_APP_KEY="env-key",
        EASYAUTH_DINGTALK_APP_SECRET="env-secret",  # noqa: S106
        EASYAUTH_DINGTALK_AGENT_ID="1001",
    ):
        executor = MigrationExecutor(connection)
        with pytest.raises(RuntimeError, match="缺少 active 完整通知通道"):
            _ = executor.migrate(_AFTER_TARGETS)

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(
        [
            ("applications", "0027_notification_channel_directory_scope"),
            ("notify", "0002_notifymessage_deeplink_title"),
        ],
    ).apps
    message_model = cast(
        "type[_MessageModel]",
        cast("object", failed_apps.get_model("notify", "NotifyMessage")),
    )
    _ = message_model.objects.all().delete()


@pytest.mark.parametrize(
    "mirror_model_name",
    ["DingTalkUserMirror", "DingTalkDepartmentMirror"],
)
def test_scope_migration_fails_without_deleting_default_channel_for_mirror_only_corp(
    mirror_model_name: str,
) -> None:
    before = _migrate(_BEFORE_TARGETS)
    _seed_directory_scope(before, source_slug="dingtalk", corp_id="corp-a")
    _seed_mirror_only_scope(
        before,
        model_name=mirror_model_name,
        source_slug="dingtalk",
        corp_id="corp-b",
    )
    apps = before.loader.project_state(_BEFORE_TARGETS).apps
    app_model = cast(
        "type[_AppModel]",
        cast("object", apps.get_model("applications", "App")),
    )
    capability_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "AppCapability")),
    )
    integration_settings = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "IntegrationSettings")),
    )
    app = app_model.objects.create(app_key="migration-multi-scope", name="Multi Scope")
    _ = capability_model.objects.create(app_id=app.id, capability="notify", enabled=True)
    _ = integration_settings.objects.create(
        id=1,
        dingtalk_app_key="db-key",
        dingtalk_app_secret="db-secret",  # noqa: S106
        dingtalk_agent_id="1001",
    )

    executor = MigrationExecutor(connection)
    with pytest.raises(RuntimeError, match="正式目录快照中的 source/corp 不唯一"):
        _ = executor.migrate(_AFTER_TARGETS)

    failed = MigrationExecutor(connection)
    migrated_apps = failed.loader.project_state(_AT_0026_TARGETS).apps
    channel_model = cast(
        "type[_ChannelModel]",
        cast("object", migrated_apps.get_model("applications", "AppNotificationChannel")),
    )
    channel = channel_model.objects.get(app_id=app.id)
    assert channel.created_by == "migration"
    assert channel.dingtalk_app_secret == "db-secret"  # noqa: S105

    mirror_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", migrated_apps.get_model("accounts", mirror_model_name)),
    )
    _ = mirror_model.objects.filter(corp_id="corp-b").delete()


def test_history_channel_inference_rejects_mirror_only_second_scope() -> None:
    before = _migrate(_BEFORE_TARGETS)
    _seed_directory_scope(before, source_slug="dingtalk", corp_id="corp-a")
    _seed_mirror_only_scope(
        before,
        model_name="DingTalkUserMirror",
        source_slug="dingtalk",
        corp_id="corp-b",
    )
    _app_id, _message_id = _seed_legacy_message(
        before,
        app_key="migration-history-multi-scope",
        capability_enabled=False,
    )

    with override_settings(
        EASYAUTH_DINGTALK_APP_KEY="env-key",
        EASYAUTH_DINGTALK_APP_SECRET="env-secret",  # noqa: S106
        EASYAUTH_DINGTALK_AGENT_ID="1001",
    ):
        executor = MigrationExecutor(connection)
        with pytest.raises(RuntimeError, match="缺少 active 完整通知通道"):
            _ = executor.migrate(_AFTER_TARGETS)

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(
        [
            ("applications", "0027_notification_channel_directory_scope"),
            ("notify", "0002_notifymessage_deeplink_title"),
        ],
    ).apps
    message_model = cast(
        "type[_MessageModel]",
        cast("object", failed_apps.get_model("notify", "NotifyMessage")),
    )
    _ = message_model.objects.all().delete()
    mirror_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", failed_apps.get_model("accounts", "DingTalkUserMirror")),
    )
    _ = mirror_model.objects.filter(corp_id="corp-b").delete()


def test_adjacent_reverse_to_0026_preserves_migration_created_channel() -> None:
    before = _migrate(_BEFORE_TARGETS)
    _seed_directory_scope(before)
    apps = before.loader.project_state(_BEFORE_TARGETS).apps
    app_model = cast(
        "type[_AppModel]",
        cast("object", apps.get_model("applications", "App")),
    )
    capability_model = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "AppCapability")),
    )
    integration_settings = cast(
        "type[_CreateOnlyModel]",
        cast("object", apps.get_model("applications", "IntegrationSettings")),
    )
    app = app_model.objects.create(app_key="migration-adjacent-reverse", name="Reverse")
    _ = capability_model.objects.create(app_id=app.id, capability="notify", enabled=True)
    _ = integration_settings.objects.create(
        id=1,
        dingtalk_app_key="reverse-key",
        dingtalk_app_secret="reverse-secret",  # noqa: S106
        dingtalk_agent_id="7007",
    )

    at_0027 = _migrate(
        [
            ("applications", "0027_notification_channel_directory_scope"),
            ("notify", "0002_notifymessage_deeplink_title"),
        ],
    )
    scoped_apps = at_0027.loader.project_state(
        [("applications", "0027_notification_channel_directory_scope")],
    ).apps
    scoped_channel_model = cast(
        "type[_ChannelModel]",
        cast("object", scoped_apps.get_model("applications", "AppNotificationChannel")),
    )
    scoped_channel = scoped_channel_model.objects.get(app_id=app.id)
    assert scoped_channel.corp_id == "migration-corp"

    at_0026 = _migrate(_AT_0026_TARGETS)
    reversed_apps = at_0026.loader.project_state(_AT_0026_TARGETS).apps
    reversed_channel_model = cast(
        "type[_ChannelModel]",
        cast("object", reversed_apps.get_model("applications", "AppNotificationChannel")),
    )
    reversed_channel = reversed_channel_model.objects.get(app_id=app.id)
    assert reversed_channel.created_by == "migration"
    assert reversed_channel.dingtalk_app_key == "reverse-key"
    assert reversed_channel.dingtalk_app_secret == "reverse-secret"  # noqa: S105
    assert reversed_channel.agent_id == "7007"

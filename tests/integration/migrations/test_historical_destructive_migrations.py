from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from django.apps.registry import Apps


_PASSWORD_HASH_MARKER = "hash"  # noqa: S105
_TOTP_MARKER = "plaintext-totp-value"
_AUTHENTIK_MARKER = "plaintext-authentik-value"
_TOKEN_HASH_MARKER = "sha256:test"  # noqa: S105
_TOKEN_LOOKUP_MARKER = "lookup"  # noqa: S105

_LATEST_TARGETS = [
    ("access_requests", "0014_access_request_relationship_triggers"),
    ("accounts", "0016_retention_indexes"),
    ("applications", "0030_dependency_health_retention_index"),
    ("audit", "0003_directory_audit_bucket"),
    ("connectors", "0004_external_group_snapshot"),
    ("grants", "0007_access_grant_relationship_triggers"),
    ("integrations", "0003_stream_raw_minimization"),
    ("lifecycle", "0005_handoverappaction_preview_generation"),
    ("notify", "0007_remove_legacy_recipient_identity"),
    ("outbox", "0002_outboxevent_outbox_status_supported_and_more"),
    ("teams", "0002_alter_teammember_user"),
    ("webhooks", "0004_raw_payload_minimization"),
    ("workflows", "0003_pendingapprovalcallback_workflows_callback_status_terminal_and_more"),
]


class _CreatedRow(Protocol):
    id: int


class _LocalAdminRow(_CreatedRow, Protocol):
    totp_secret: str
    totp_enabled: bool


class _IntegrationSettingsRow(_CreatedRow, Protocol):
    authentik_api_token: str


class _AccessGrantRow(_CreatedRow, Protocol):
    version: int


class _DingTalkUserRow(_CreatedRow, Protocol):
    status: str


class _DeleteQuerySet(Protocol):
    def count(self) -> int: ...

    def delete(self) -> tuple[int, dict[str, int]]: ...


class _HistoricalManager(Protocol):
    def create(self, **kwargs: object) -> _CreatedRow: ...

    def filter(self, **kwargs: object) -> _DeleteQuerySet: ...

    def get(self, **kwargs: object) -> _CreatedRow: ...


class _HistoricalModel(Protocol):
    objects: _HistoricalManager


@pytest.fixture(autouse=True)
def restore_latest_migrations() -> Iterator[None]:
    _restore_latest_schema()
    try:
        yield
    finally:
        _restore_latest_schema()


def test_access_request_idempotency_migration_blocks_existing_requests_without_delete() -> None:
    before_targets = [
        ("applications", "0030_dependency_health_retention_index"),
        ("accounts", "0016_retention_indexes"),
        ("access_requests", "0008_delete_access_request_role"),
    ]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    app = _model(state_apps, "applications", "App").objects.create(
        app_key="ea-aud-023-request",
        name="EA-AUD-023 Request",
    )
    user = _model(state_apps, "accounts", "UserMirror").objects.create(
        authentik_user_id="ea-aud-023-request-user",
    )
    request = _model(state_apps, "access_requests", "AccessRequest").objects.create(
        app_id=app.id,
        user_id=user.id,
        status="submitted",
        reason="历史申请必须保留",
    )

    with pytest.raises(RuntimeError, match=r"access_requests\.0009"):
        _ = MigrationExecutor(connection).migrate(
            [("access_requests", "0009_access_request_idempotency")]
        )

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    request_model = _model(failed_apps, "access_requests", "AccessRequest")
    assert request_model.objects.filter(id=request.id).count() == 1
    _ = request_model.objects.filter(id=request.id).delete()


def test_grant_membership_expiration_migration_blocks_existing_grants_without_delete() -> None:
    before_targets = [
        ("applications", "0030_dependency_health_retention_index"),
        ("accounts", "0016_retention_indexes"),
        ("grants", "0004_delete_access_grant_role"),
    ]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    app = _model(state_apps, "applications", "App").objects.create(
        app_key="ea-aud-023-grant",
        name="EA-AUD-023 Grant",
    )
    user = _model(state_apps, "accounts", "UserMirror").objects.create(
        authentik_user_id="ea-aud-023-grant-user",
    )
    grant = _model(state_apps, "grants", "AccessGrant").objects.create(
        app_id=app.id,
        user_id=user.id,
        grant_type="permanent",
        grant_expires_at=None,
        status="active",
        is_current=True,
    )

    with pytest.raises(RuntimeError, match=r"grants\.0005"):
        _ = MigrationExecutor(connection).migrate([("grants", "0005_membership_expiration")])

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    grant_model = _model(failed_apps, "grants", "AccessGrant")
    assert grant_model.objects.filter(id=grant.id).count() == 1
    _ = grant_model.objects.filter(id=grant.id).delete()


def test_totp_encryption_migration_blocks_plaintext_secret_without_clear() -> None:
    before_targets = [("accounts", "0006_localadminaccount_must_change_password")]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    account = _model(state_apps, "accounts", "LocalAdminAccount").objects.create(
        username="ea-aud-023-admin",
        password_hash=_PASSWORD_HASH_MARKER,
        totp_secret=_TOTP_MARKER,
        totp_enabled=True,
        must_change_password=False,
    )

    with pytest.raises(RuntimeError, match=r"accounts\.0007"):
        _ = MigrationExecutor(connection).migrate(
            [("accounts", "0007_alter_localadminaccount_totp_secret")]
        )

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    account_model = _model(failed_apps, "accounts", "LocalAdminAccount")
    preserved = cast("_LocalAdminRow", account_model.objects.get(id=account.id))
    assert preserved.totp_secret == _TOTP_MARKER
    assert preserved.totp_enabled is True
    _ = account_model.objects.filter(id=account.id).delete()


def test_authentik_token_migration_blocks_plaintext_token_without_clear() -> None:
    before_targets = [("applications", "0014_integrationsettings")]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    settings = _model(state_apps, "applications", "IntegrationSettings").objects.create(
        authentik_base_url="https://authentik.example.test",
        authentik_api_token=_AUTHENTIK_MARKER,
        updated_by="ea-aud-023",
    )

    with pytest.raises(RuntimeError, match=r"applications\.0015"):
        _ = MigrationExecutor(connection).migrate(
            [("applications", "0015_alter_integrationsettings_authentik_api_token")]
        )

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    settings_model = _model(failed_apps, "applications", "IntegrationSettings")
    preserved = cast("_IntegrationSettingsRow", settings_model.objects.get(id=settings.id))
    assert preserved.authentik_api_token == _AUTHENTIK_MARKER
    _ = settings_model.objects.filter(id=settings.id).delete()


def test_approval_rule_target_unique_migration_blocks_duplicates_without_delete() -> None:
    before_targets = [
        ("applications", "0011_app_credential_token_lookup"),
    ]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    app = _model(state_apps, "applications", "App").objects.create(
        app_key="ea-aud-023-approval-rule",
        name="EA-AUD-023 Approval Rule",
    )
    permission = _model(state_apps, "applications", "Permission").objects.create(
        app_id=app.id,
        key="read",
        name="Read",
        supported_scopes=["GLOBAL"],
    )
    rule_model = _model(state_apps, "applications", "ApprovalRule")
    first_rule = rule_model.objects.create(
        app_id=app.id,
        permission_id=permission.id,
        approver_userids=["approver-a"],
    )
    second_rule = rule_model.objects.create(
        app_id=app.id,
        permission_id=permission.id,
        approver_userids=["approver-b"],
    )

    with pytest.raises(RuntimeError, match=r"applications\.0012"):
        _ = MigrationExecutor(connection).migrate(
            [("applications", "0012_approval_rule_target_unique")]
        )

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    failed_rule_model = _model(failed_apps, "applications", "ApprovalRule")
    assert failed_rule_model.objects.filter(id=first_rule.id).count() == 1
    assert failed_rule_model.objects.filter(id=second_rule.id).count() == 1
    _ = failed_rule_model.objects.filter(id__in=[first_rule.id, second_rule.id]).delete()


def test_grant_version_unique_migration_blocks_duplicates_without_renumber() -> None:
    before_targets = [
        ("applications", "0030_dependency_health_retention_index"),
        ("accounts", "0016_retention_indexes"),
        ("grants", "0002_scoped_grants"),
    ]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    app = _model(state_apps, "applications", "App").objects.create(
        app_key="ea-aud-023-grant-version",
        name="EA-AUD-023 Grant Version",
    )
    user = _model(state_apps, "accounts", "UserMirror").objects.create(
        authentik_user_id="ea-aud-023-grant-version-user",
    )
    grant_model = _model(state_apps, "grants", "AccessGrant")
    first_grant = grant_model.objects.create(
        app_id=app.id,
        user_id=user.id,
        grant_type="permanent",
        grant_expires_at=None,
        status="active",
        is_current=True,
        version=1,
    )
    second_grant = grant_model.objects.create(
        app_id=app.id,
        user_id=user.id,
        grant_type="permanent",
        grant_expires_at=None,
        status="revoked",
        is_current=False,
        version=1,
    )

    with pytest.raises(RuntimeError, match=r"grants\.0003"):
        _ = MigrationExecutor(connection).migrate([("grants", "0003_access_grant_version_unique")])

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    failed_grant_model = _model(failed_apps, "grants", "AccessGrant")
    preserved = cast("_AccessGrantRow", failed_grant_model.objects.get(id=second_grant.id))
    assert preserved.version == 1
    assert failed_grant_model.objects.filter(id=first_grant.id).count() == 1
    _ = failed_grant_model.objects.filter(id__in=[first_grant.id, second_grant.id]).delete()


def test_directory_status_migration_blocks_unknown_status_without_downgrade() -> None:
    before_targets = [("accounts", "0012_app_capability_and_directory_indexes")]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    mirror = _model(state_apps, "accounts", "DingTalkUserMirror").objects.create(
        source_slug="dingtalk",
        corp_id="ea-aud-023-corp",
        user_id="ea-aud-023-user",
        status="inactive",
    )

    with pytest.raises(RuntimeError, match=r"accounts\.0013"):
        _ = MigrationExecutor(connection).migrate(
            [("accounts", "0013_directory_user_contact_tombstones")]
        )

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    mirror_model = _model(failed_apps, "accounts", "DingTalkUserMirror")
    preserved = cast("_DingTalkUserRow", mirror_model.objects.get(id=mirror.id))
    assert preserved.status == "inactive"
    _ = mirror_model.objects.filter(id=mirror.id).delete()


def test_credential_capability_migration_blocks_implicit_authorization() -> None:
    before_targets = [
        (
            "applications",
            "0024_remove_dependencyhealthsnapshot_applications_dependency_health_dependency_supported_and_more",
        ),
    ]
    before = _migrate(before_targets)
    state_apps = before.loader.project_state(before_targets).apps
    app = _model(state_apps, "applications", "App").objects.create(
        app_key="ea-aud-023-credential-capability",
        name="EA-AUD-023 Credential Capability",
    )
    _ = _model(state_apps, "applications", "AppCapability").objects.create(
        app_id=app.id,
        capability="directory",
        enabled=True,
    )
    credential = _model(state_apps, "applications", "AppCredential").objects.create(
        app_id=app.id,
        credential_type="static_token",
        name="历史凭据",
        token_hash=_TOKEN_HASH_MARKER,
        token_lookup=_TOKEN_LOOKUP_MARKER,
        is_active=True,
    )

    with pytest.raises(RuntimeError, match=r"applications\.0025"):
        _ = MigrationExecutor(connection).migrate(
            [("applications", "0025_credential_capabilities")]
        )

    failed = MigrationExecutor(connection)
    failed_apps = failed.loader.project_state(before_targets).apps
    credential_model = _model(failed_apps, "applications", "AppCredential")
    assert credential_model.objects.filter(id=credential.id).count() == 1
    _ = credential_model.objects.filter(id=credential.id).delete()


def test_empty_database_full_migration_replay_succeeds() -> None:
    _ = MigrationExecutor(connection).migrate([])
    fresh_executor = MigrationExecutor(connection)
    _ = fresh_executor.migrate(_leaf_nodes(fresh_executor))


def _migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    _restore_latest_schema()
    executor = MigrationExecutor(connection)
    _ = executor.migrate(targets)
    return MigrationExecutor(connection)


def _model(apps: Apps, app_label: str, model_name: str) -> _HistoricalModel:
    return cast("_HistoricalModel", apps.get_model(app_label, model_name))


def _leaf_nodes(executor: MigrationExecutor) -> list[tuple[str, str]]:
    return cast(
        "list[tuple[str, str]]",
        executor.loader.graph.leaf_nodes(),  # pyright: ignore[reportAny]
    )


def _restore_latest_schema() -> None:
    connection.close()
    executor = MigrationExecutor(connection)
    _ = executor.migrate(_leaf_nodes(executor))
    connection.close()

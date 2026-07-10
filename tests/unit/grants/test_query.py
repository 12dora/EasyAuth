from __future__ import annotations

from datetime import timedelta
from typing import Final

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.managed_users import ManagedUsersResolutionUnavailableError
from easyauth.grants.models import (
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.grants.query import (
    ExpandedGrant,
    GroupSnapshot,
    ResolvedManagedUsers,
    _resolved_digest,
    resolve_user_permissions,
)
from easyauth.integrations.authentik.directory_client import AuthentikDirectoryUnavailableError
from easyauth.integrations.authentik.directory_payloads import DingTalkManagedUsers

pytestmark = pytest.mark.django_db

REVOKED_VERSION: Final = 2
EXPIRED_VERSION: Final = 3
UNKNOWN_USER_CATALOG_VERSION: Final = 12


def test_resolve_user_permissions_expands_group_grants_and_sorts_groups_and_grants() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-resolve-groups")
    app = App.objects.create(app_key="resolve-groups-app", name="Resolve Groups App")
    _scope(app, "SELF")
    _scope(app, "TEAM")
    sales = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="销售")
    finance = AuthorizationGroup.objects.create(app=app, key="finance", kind="bundle", name="财务")
    approve = _permission(app, "invoice.approve", scopes=["TEAM"])
    read = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=sales,
        permission=read,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=finance,
        permission=approve,
        scope_key="TEAM",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=sales,
        expires_at=None,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=finance,
        expires_at=None,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.user_id == "user-resolve-groups"
    assert snapshot.app_key == "resolve-groups-app"
    assert snapshot.grant_version == 1
    assert snapshot.catalog_version == 1
    assert snapshot.snapshot_version == (
        f"1.1.{_resolved_digest(snapshot.grants, snapshot.groups)}"
    )
    assert snapshot.groups == (
        GroupSnapshot(key="finance", kind="bundle", name="财务", expires_at=None),
        GroupSnapshot(key="sales", kind="role", name="销售", expires_at=None),
    )
    assert snapshot.grants == (
        ExpandedGrant(
            permission="invoice.approve",
            scope="TEAM",
            source_type="group",
            source_key="finance",
            expires_at=None,
        ),
        ExpandedGrant(
            permission="invoice.read",
            scope="SELF",
            source_type="group",
            source_key="sales",
            expires_at=None,
        ),
    )


def test_resolve_user_permissions_expands_direct_scoped_grants() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-direct-scoped")
    app = App.objects.create(app_key="direct-scoped-app", name="Direct Scoped App")
    _scope(app, "SELF")
    permission = _permission(app, "customer.profile.export", scopes=["SELF"])
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
        expires_at=None,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.groups == ()
    assert snapshot.grants == (
        ExpandedGrant(
            permission="customer.profile.export",
            scope="SELF",
            source_type="direct",
            source_key="",
            expires_at=None,
        ),
    )


def test_resolve_user_permissions_preserves_same_permission_with_different_scopes() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-multi-scope")
    app = App.objects.create(app_key="multi-scope-app", name="Multi Scope App")
    _scope(app, "SELF")
    _scope(app, "TEAM")
    permission = _permission(app, "invoice.read", scopes=["SELF", "TEAM"])
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="TEAM",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
        expires_at=None,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grants == (
        ExpandedGrant("invoice.read", "SELF", "direct", "", None),
        ExpandedGrant("invoice.read", "TEAM", "direct", "", None),
    )


def test_resolve_user_permissions_keeps_group_and_direct_sources_for_same_scope() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-mixed-source")
    app = App.objects.create(app_key="mixed-source-app", name="Mixed Source App")
    _scope(app, "SELF")
    group = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="Sales")
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
        expires_at=None,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grants == (
        ExpandedGrant("invoice.read", "SELF", "direct", "", None),
        ExpandedGrant("invoice.read", "SELF", "group", "sales", None),
    )


def test_resolve_user_permissions_preserves_per_item_expiration_across_sources() -> None:
    # Given: 同一权限由永久组成员关系和限时直接授权同时提供。
    user = UserMirror.objects.create(authentik_user_id="user-mixed-expiration")
    app = App.objects.create(app_key="mixed-expiration-app", name="Mixed Expiration App")
    _scope(app, "SELF")
    group = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="Sales")
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    timed_expires_at = timezone.now() + timedelta(hours=1)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
        expires_at=timed_expires_at,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then: 永久项不把限时项提升为永久, 两个来源保留各自期限。
    assert snapshot.groups == (
        GroupSnapshot(key="sales", kind="role", name="Sales", expires_at=None),
    )
    assert snapshot.grants == (
        ExpandedGrant("invoice.read", "SELF", "direct", "", timed_expires_at),
        ExpandedGrant("invoice.read", "SELF", "group", "sales", None),
    )


def test_resolve_user_permissions_filters_expiration_per_item_within_each_source() -> None:
    # Given: 组来源和直接来源都同时包含永久项与已过期项。
    user = UserMirror.objects.create(authentik_user_id="user-per-item-expiration")
    app = App.objects.create(app_key="per-item-expiration-app", name="Per Item Expiration App")
    _scope(app, "SELF")
    active_group = AuthorizationGroup.objects.create(
        app=app,
        key="active-group",
        kind="role",
        name="Active Group",
    )
    expired_group = AuthorizationGroup.objects.create(
        app=app,
        key="expired-group",
        kind="role",
        name="Expired Group",
    )
    group_active_permission = _permission(app, "group.active", scopes=["SELF"])
    group_expired_permission = _permission(app, "group.expired", scopes=["SELF"])
    direct_active_permission = _permission(app, "direct.active", scopes=["SELF"])
    direct_expired_permission = _permission(app, "direct.expired", scopes=["SELF"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=group_active_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=expired_group,
        permission=group_expired_permission,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    expired_at = timezone.now() - timedelta(minutes=1)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=active_group,
        expires_at=None,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=expired_group,
        expires_at=expired_at,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=direct_active_permission,
        scope_key="SELF",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=direct_expired_permission,
        scope_key="SELF",
        expires_at=expired_at,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then: 同来源的永久项只保留自身, 不抬升已过期项。
    assert snapshot.groups == (
        GroupSnapshot(
            key="active-group",
            kind="role",
            name="Active Group",
            expires_at=None,
        ),
    )
    assert snapshot.grants == (
        ExpandedGrant("direct.active", "SELF", "direct", "", None),
        ExpandedGrant("group.active", "SELF", "group", "active-group", None),
    )


def test_expanded_grant_supports_optional_resolved_managed_users_contract() -> None:
    # Given
    resolved = ResolvedManagedUsers(
        user_ids=("user-001", "user-002"),
        resolver="manual",
        resolved_at="2026-06-05T10:20:30Z",
    )

    # When
    regular_grant = ExpandedGrant("invoice.read", "SELF", "direct", "", None)
    managed_users_grant = ExpandedGrant(
        "invoice.read",
        "MANAGED_USERS",
        "direct",
        "",
        None,
        resolved=resolved,
    )

    # Then
    assert regular_grant.resolved is None
    assert managed_users_grant.resolved == resolved


def test_resolve_user_permissions_resolves_managed_users_with_effective_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 用户持有 MANAGED_USERS 授权组, App 配置了有效管理范围策略。
    user = UserMirror.objects.create(
        authentik_user_id="manager-ak",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="manager-dt",
    )
    app = App.objects.create(app_key="crm-managed-query", name="CRM")
    _scope(app, "MANAGED_USERS")
    permission = _permission(app, "customer.profile.view", scopes=["MANAGED_USERS"])
    group = AuthorizationGroup.objects.create(app=app, key="team-manager", kind="role", name="主管")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    monkeypatch.setattr(
        "easyauth.grants.managed_users.AuthentikDirectoryClient.from_settings",
        lambda: _ManagedUsersClient(("employee-1", "manager-ak", "employee-2")),
    )

    # When: 查询用户权限。
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then: MANAGED_USERS grant 带 resolved, 且不包含当前用户本人。
    assert snapshot.grants == (
        ExpandedGrant(
            permission="customer.profile.view",
            scope="MANAGED_USERS",
            source_type="group",
            source_key="team-manager",
            expires_at=None,
            resolved=ResolvedManagedUsers(
                user_ids=("employee-1", "employee-2"),
                resolver="dingtalk_manager_chain",
                resolved_at="2026-07-02T12:00:00+08:00",
            ),
        ),
    )
    # 热查询路径的成功解析不再逐次写审计, 避免读接口成为审计表写放大器。
    assert not AuditLog.objects.filter(event_type="managed_users_resolution_succeeded").exists()


def test_resolve_user_permissions_filters_managed_users_grant_without_effective_policy() -> None:
    # Given: 用户持有 MANAGED_USERS 授权组, 但 App 没有有效策略。
    user = UserMirror.objects.create(
        authentik_user_id="manager-no-policy",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="manager-dt",
    )
    app = App.objects.create(app_key="crm-managed-no-policy", name="CRM")
    _scope(app, "MANAGED_USERS")
    permission = _permission(app, "customer.profile.view", scopes=["MANAGED_USERS"])
    group = AuthorizationGroup.objects.create(app=app, key="team-manager", kind="role", name="主管")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )

    # When: 查询用户权限。
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then: 无有效策略时该 MANAGED_USERS grant 不生效。
    assert snapshot.grants == ()
    audit_log = AuditLog.objects.get(event_type="managed_users_resolution_failed")
    assert audit_log.actor_type == "system"
    assert audit_log.actor_id == "managed_users_resolver"
    assert audit_log.target_type == "authorization_group_grant"
    assert audit_log.metadata == {
        "app_key": app.app_key,
        "authorization_group_key": group.key,
        "permission_key": permission.key,
        "scope": "MANAGED_USERS",
        "resolver": "missing",
        "error_code": "managed_scope_policy_missing",
    }


def test_resolve_user_permissions_keeps_managed_users_grant_when_resolved_users_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 策略有效, 但下级列表为空。
    user = UserMirror.objects.create(
        authentik_user_id="manager-empty",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="manager-dt",
    )
    app = App.objects.create(app_key="crm-managed-empty", name="CRM")
    _scope(app, "MANAGED_USERS")
    permission = _permission(app, "customer.profile.view", scopes=["MANAGED_USERS"])
    group = AuthorizationGroup.objects.create(app=app, key="team-manager", kind="role", name="主管")
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    monkeypatch.setattr(
        "easyauth.grants.managed_users.AuthentikDirectoryClient.from_settings",
        lambda: _ManagedUsersClient(()),
    )

    # When: 查询用户权限。
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then: 策略有效但结果为空时保留 grant 并返回空 resolved。
    assert snapshot.grants[0].resolved == ResolvedManagedUsers(
        user_ids=(),
        resolver="dingtalk_manager_chain",
        resolved_at="2026-07-02T12:00:00+08:00",
    )


def test_resolve_user_permissions_filters_inactive_and_deprecated_catalog_entries() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-filtered-catalog")
    app = App.objects.create(app_key="filtered-catalog-app", name="Filtered Catalog App")
    _scope(app, "SELF")
    _scope(app, "INACTIVE", is_active=False)
    active_group = AuthorizationGroup.objects.create(
        app=app,
        key="active",
        kind="role",
        name="Active",
    )
    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="inactive",
        kind="role",
        name="Inactive",
        is_active=False,
    )
    active_permission = _permission(app, "invoice.active", scopes=["SELF"])
    inactive_permission = _permission(app, "invoice.inactive", scopes=["SELF"], is_active=False)
    deprecated_permission = _permission(
        app,
        "invoice.deprecated",
        scopes=["SELF"],
        deprecated_at=timezone.now(),
    )
    inactive_scope_permission = _permission(app, "invoice.inactive-scope", scopes=["INACTIVE"])
    inactive_group_permission = _permission(app, "invoice.inactive-group", scopes=["SELF"])
    inactive_group_grant_permission = _permission(
        app,
        "invoice.inactive-group-grant",
        scopes=["SELF"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=active_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=deprecated_permission,
        scope_key="SELF",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_scope_permission,
        scope_key="INACTIVE",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=active_group,
        permission=inactive_group_grant_permission,
        scope_key="SELF",
        is_active=False,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=inactive_group,
        permission=inactive_group_permission,
        scope_key="SELF",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=active_group,
        expires_at=None,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=inactive_group,
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=active_permission,
        scope_key="SELF",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=inactive_permission,
        scope_key="SELF",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=deprecated_permission,
        scope_key="SELF",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=inactive_scope_permission,
        scope_key="INACTIVE",
        expires_at=None,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.groups == (
        GroupSnapshot(key="active", kind="role", name="Active", expires_at=None),
    )
    assert snapshot.grants == (
        ExpandedGrant("invoice.active", "SELF", "direct", "", None),
        ExpandedGrant("invoice.active", "SELF", "group", "active", None),
    )


def test_resolve_user_permissions_returns_catalog_and_snapshot_versions_for_empty_results() -> None:
    # Given
    app = App.objects.create(
        app_key="unknown-user-resolve-app",
        name="Unknown User App",
        catalog_version=UNKNOWN_USER_CATALOG_VERSION,
    )

    # When
    snapshot = resolve_user_permissions(user="unknown-user-resolve", app=app)

    # Then
    assert snapshot.user_id == "unknown-user-resolve"
    assert snapshot.app_key == "unknown-user-resolve-app"
    assert snapshot.grant_version == 0
    assert snapshot.catalog_version == UNKNOWN_USER_CATALOG_VERSION
    assert snapshot.snapshot_version == "0.12.0"
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_resolve_user_permissions_returns_empty_for_disabled_user() -> None:
    # Given
    user = UserMirror.objects.create(
        authentik_user_id="user-disabled-resolve",
        status="disabled",
    )
    app = App.objects.create(app_key="disabled-resolve-app", name="Disabled Resolve App")
    _scope(app, "SELF")
    grant = AccessGrant.objects.create(user=user, app=app)
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
        expires_at=None,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grant_version == 1
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_resolve_user_permissions_returns_empty_for_departed_user() -> None:
    # Given
    user = UserMirror.objects.create(
        authentik_user_id="user-departed-resolve",
        status="departed",
    )
    app = App.objects.create(app_key="departed-resolve-app", name="Departed Resolve App")
    _scope(app, "SELF")
    grant = AccessGrant.objects.create(user=user, app=app)
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
        expires_at=None,
    )

    # When
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then
    assert snapshot.grant_version == 1
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_resolve_user_permissions_returns_empty_for_revoked_or_expired_grant() -> None:
    # Given
    revoked_user = UserMirror.objects.create(authentik_user_id="user-revoked-resolve")
    expired_user = UserMirror.objects.create(authentik_user_id="user-expired-resolve")
    app = App.objects.create(app_key="inactive-grant-resolve-app", name="Inactive Grant App")
    _scope(app, "SELF")
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    revoked = AccessGrant.objects.create(
        user=revoked_user,
        app=app,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
        version=REVOKED_VERSION,
    )
    expired = AccessGrant.objects.create(
        user=expired_user,
        app=app,
        status=GRANT_STATUS_EXPIRED,
        is_current=False,
        version=EXPIRED_VERSION,
    )
    _ = AccessGrantPermission.objects.create(
        grant=revoked,
        permission=permission,
        scope_key="SELF",
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=expired,
        permission=permission,
        scope_key="SELF",
        expires_at=None,
    )

    # When
    revoked_snapshot = resolve_user_permissions(user=revoked_user, app=app)
    expired_snapshot = resolve_user_permissions(user=expired_user, app=app)

    # Then
    assert revoked_snapshot.grant_version == REVOKED_VERSION
    assert revoked_snapshot.groups == ()
    assert revoked_snapshot.grants == ()
    assert expired_snapshot.grant_version == EXPIRED_VERSION
    assert expired_snapshot.groups == ()
    assert expired_snapshot.grants == ()


def _scope(app: App, key: str, *, is_active: bool = True) -> AppScope:
    return AppScope.objects.create(app=app, key=key, name=key.title(), is_active=is_active)


def _permission(
    app: App,
    key: str,
    *,
    scopes: list[str],
    is_active: bool = True,
    deprecated_at: object | None = None,
) -> Permission:
    return Permission.objects.create(
        app=app,
        key=key,
        name=key,
        supported_scopes=scopes,
        is_active=is_active,
        deprecated_at=deprecated_at,
    )


class _ManagedUsersClient:
    def __init__(self, user_ids: tuple[str, ...]) -> None:
        self._user_ids = user_ids

    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        assert corp_id == "corp-1"
        assert manager_user_id == "manager-dt"
        return DingTalkManagedUsers(
            source_slug="dingtalk",
            corp_id=corp_id,
            manager_user_id=manager_user_id,
            resolver="dingtalk_manager_chain",
            stale=False,
            resolved_at="2026-07-02T12:00:00+08:00",
            users=(),
            active_authentik_user_ids=self._user_ids,
        )


def test_resolve_user_permissions_returns_empty_for_expired_permission_item() -> None:
    # Given: 直接权限项已过期, 但清理任务尚未删除该链接。
    user = UserMirror.objects.create(authentik_user_id="user-time-expired")
    app = App.objects.create(app_key="time-expired-app", name="Time Expired App")
    _scope(app, "SELF")
    permission = _permission(app, "invoice.read", scopes=["SELF"])
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    # When: 查询用户权限。
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then: 查询路径直接按逐项过期时间判定, 不再返回权限。
    assert snapshot.groups == ()
    assert snapshot.grants == ()


def test_group_without_expanded_permission_changes_snapshot_version_when_it_expires() -> None:
    # Given: 当前授权组没有可展开权限, 但组成员事实本身仍属于下游快照。
    user = UserMirror.objects.create(authentik_user_id="user-group-only-expiration")
    app = App.objects.create(app_key="group-only-expiration-app", name="Group Only")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="empty-group",
        kind="role",
        name="Empty Group",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    expires_at = timezone.now() + timedelta(hours=1)
    link = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=expires_at,
    )

    # When: 先读取有效快照, 再模拟清理任务尚未运行时该组已经过期。
    active_snapshot = resolve_user_permissions(user=user, app=app)
    link.expires_at = timezone.now() - timedelta(seconds=1)
    link.save(update_fields=["expires_at"])
    expired_snapshot = resolve_user_permissions(user=user, app=app)

    # Then: 即使没有 expanded grants, 组事实消失也会改变 snapshot_version。
    assert active_snapshot.grants == ()
    assert active_snapshot.groups == (
        GroupSnapshot(
            key="empty-group",
            kind="role",
            name="Empty Group",
            expires_at=expires_at,
        ),
    )
    assert active_snapshot.snapshot_version == (
        f"1.1.{_resolved_digest(active_snapshot.grants, active_snapshot.groups)}"
    )
    assert expired_snapshot.groups == ()
    assert expired_snapshot.grants == ()
    assert expired_snapshot.snapshot_version == "1.1.0"
    assert expired_snapshot.snapshot_version != active_snapshot.snapshot_version


class _UnavailableManagedUsersClient:
    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        _ = corp_id, manager_user_id
        message = "目录不可用"
        raise AuthentikDirectoryUnavailableError(message)


class _CountingManagedUsersClient(_ManagedUsersClient):
    def __init__(self, user_ids: tuple[str, ...]) -> None:
        super().__init__(user_ids)
        self.call_count = 0

    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        self.call_count += 1
        return super().get_managed_users(corp_id, manager_user_id)


def _managed_users_app(
    app_key: str,
    user_suffix: str,
    *,
    grant_count: int = 1,
) -> tuple[UserMirror, App]:
    user = UserMirror.objects.create(
        authentik_user_id=f"manager-{user_suffix}",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="manager-dt",
    )
    app = App.objects.create(app_key=app_key, name="CRM")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="管理范围")
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    for index in range(grant_count):
        permission = _permission(app, f"customer.view.{index}", scopes=["MANAGED_USERS"])
        group = AuthorizationGroup.objects.create(
            app=app,
            key=f"team-manager-{index}",
            kind="role",
            name=f"主管{index}",
        )
        _ = AuthorizationGroupGrant.objects.create(
            authorization_group=group,
            permission=permission,
            scope_key="MANAGED_USERS",
        )
        _ = AccessGrantGroup.objects.create(
            grant=grant,
            authorization_group=group,
            expires_at=None,
        )
    return user, app


def test_resolve_user_permissions_raises_when_directory_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 策略有效, 但 Authentik 目录瞬时不可用。
    user, app = _managed_users_app("crm-managed-unavailable", "unavailable")
    monkeypatch.setattr(
        "easyauth.grants.managed_users.AuthentikDirectoryClient.from_settings",
        lambda: _UnavailableManagedUsersClient(),
    )

    # When / Then: 查询必须失败, 不允许把缺失的 MANAGED_USERS 当作成功响应下发。
    with pytest.raises(ManagedUsersResolutionUnavailableError):
        _ = resolve_user_permissions(user=user, app=app)
    audit_log = AuditLog.objects.get(event_type="managed_users_resolution_failed")
    assert audit_log.metadata["error_code"] == "managed_scope_directory_unavailable"


MANAGED_GRANT_LINK_COUNT: Final = 3


def test_resolve_user_permissions_reuses_directory_result_across_grants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 同一用户持有 3 个 MANAGED_USERS 授权链接。
    user, app = _managed_users_app(
        "crm-managed-cache",
        "cache",
        grant_count=MANAGED_GRANT_LINK_COUNT,
    )
    client = _CountingManagedUsersClient(("employee-1",))
    monkeypatch.setattr(
        "easyauth.grants.managed_users.AuthentikDirectoryClient.from_settings",
        lambda: client,
    )

    # When: 单次权限查询。
    snapshot = resolve_user_permissions(user=user, app=app)

    # Then: 目录 HTTP 只发一次, 三个 grant 共享同一份解析结果。
    assert len(snapshot.grants) == MANAGED_GRANT_LINK_COUNT
    assert client.call_count == 1


def test_resolved_digest_changes_when_managed_user_set_or_expiration_changes() -> None:
    def _grant(user_ids: tuple[str, ...]) -> ExpandedGrant:
        return ExpandedGrant(
            permission="customer.read",
            scope="MANAGED_USERS",
            source_type="direct",
            source_key="",
            expires_at=None,
            resolved=ResolvedManagedUsers(
                user_ids=user_ids,
                resolver="dingtalk_manager_chain",
                resolved_at="2026-07-02T12:00:00+08:00",
            ),
        )

    base = _resolved_digest((_grant(("u1", "u2")),))
    # 顺序不同、内容相同 -> 摘要稳定。
    assert base == _resolved_digest((_grant(("u2", "u1")),))
    # 下属集合变化 -> 摘要变化(下游 etag/缓存据此失效)。
    assert base != _resolved_digest((_grant(("u1", "u2", "u3")),))
    # 普通授权也把逐项期限纳入摘要, 只有空授权集使用固定 "0"。
    plain = ExpandedGrant(
        permission="p",
        scope="SELF",
        source_type="direct",
        source_key="",
        expires_at=None,
    )
    timed = ExpandedGrant(
        permission="p",
        scope="SELF",
        source_type="direct",
        source_key="",
        expires_at=timezone.now() + timedelta(hours=1),
    )
    assert _resolved_digest((plain,)) != _resolved_digest((timed,))
    assert _resolved_digest(()) == "0"

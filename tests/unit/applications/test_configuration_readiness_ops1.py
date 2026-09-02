from __future__ import annotations

import pytest

from easyauth.applications.configuration import (
    ACTIVE_CREDENTIAL_MISSING_MESSAGE,
    CONFIGURATION_STATUS_BLOCKING,
    CONFIGURATION_STATUS_READY,
    CONFIGURATION_STATUS_WARNING,
    configuration_readiness_for_app,
    configuration_readiness_statuses_for_apps,
)
from easyauth.applications.models import (
    App,
    AppCredential,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
    PermissionGroup,
)
from easyauth.applications.services import AppCredentialService
from easyauth.connectors.models import ConnectorInstance

pytestmark = pytest.mark.django_db


def test_ops1_configuration_readiness_blocks_active_app_without_catalog_owner_or_credentials() -> (
    None
):
    # Given: 一个 active App 还没有任何授权目录、负责人和可用凭据。
    app = App.objects.create(app_key="ops1-empty-app", name="OPS1 Empty App")

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 结果阻止发布, 并明确指出缺少 active Permission、AuthorizationGroup、owner 和凭据。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert {issue.code for issue in readiness.issues} == {
        "active_credential_missing",
        "active_permission_missing",
        "active_authorization_group_missing",
        "active_owner_missing",
    }
    assert {issue.severity for issue in readiness.issues} == {CONFIGURATION_STATUS_BLOCKING}
    assert any(
        issue.code == "active_credential_missing"
        and issue.message == ACTIVE_CREDENTIAL_MISSING_MESSAGE
        for issue in readiness.issues
    )


def test_ops1_configuration_readiness_skips_credential_when_connector_enabled() -> None:
    # Given: 连接器供给的 App 已启用 ConnectorInstance, 但没有入站 API 凭据。
    app = App.objects.create(app_key="ops1-connector-provisioned", name="OPS1 Connector")
    _ = _ready_catalog(app, approval_rule=True)
    _ = AppCredential.objects.filter(app=app).delete()
    _ = ConnectorInstance.objects.create(app=app, connector_key="netbird", enabled=True)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 出站供给不要求入站凭据, 配置完整性为 ready。
    assert readiness.status == CONFIGURATION_STATUS_READY
    assert "active_credential_missing" not in {issue.code for issue in readiness.issues}
    assert readiness.issues == ()


def test_ops1_configuration_readiness_blocks_credential_when_connector_disabled() -> None:
    # Given: App 有 ConnectorInstance 但未启用, 且没有入站 API 凭据。
    app = App.objects.create(app_key="ops1-connector-disabled", name="OPS1 Connector Disabled")
    _ = _ready_catalog(app, approval_rule=True)
    _ = AppCredential.objects.filter(app=app).delete()
    _ = ConnectorInstance.objects.create(app=app, connector_key="netbird", enabled=False)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 未启用的连接器不能替代入站凭据, 仍因缺少凭据阻塞。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert [issue.code for issue in readiness.issues] == ["active_credential_missing"]
    assert readiness.issues[0].message == ACTIVE_CREDENTIAL_MISSING_MESSAGE


def test_ops1_configuration_readiness_statuses_skip_credential_for_enabled_connector() -> None:
    # Given: 三个其余配置齐全的 App, 分别是启用连接器、停用连接器、完全没有连接器。
    provisioned = App.objects.create(app_key="ops1-bulk-connector-on", name="Bulk Connector On")
    disabled = App.objects.create(app_key="ops1-bulk-connector-off", name="Bulk Connector Off")
    pull_app = App.objects.create(app_key="ops1-bulk-no-connector", name="Bulk No Connector")
    for app in (provisioned, disabled, pull_app):
        _ = _ready_catalog(app, approval_rule=True)
        _ = AppCredential.objects.filter(app=app).delete()
    _ = ConnectorInstance.objects.create(app=provisioned, connector_key="netbird", enabled=True)
    _ = ConnectorInstance.objects.create(app=disabled, connector_key="netbird", enabled=False)

    # When: 列表批量计算配置完整性。
    statuses = configuration_readiness_statuses_for_apps((provisioned, disabled, pull_app))

    # Then: 只有启用连接器的 App 不因缺少入站凭据被标为 blocking。
    assert statuses[provisioned.id] == CONFIGURATION_STATUS_READY
    assert statuses[disabled.id] == CONFIGURATION_STATUS_BLOCKING
    assert statuses[pull_app.id] == CONFIGURATION_STATUS_BLOCKING


def test_ops1_configuration_readiness_blocks_requestable_authorization_group_without_rule() -> None:
    # Given: 可申请授权组已有 grant、凭据和 owner, 但没有 active ApprovalRule。
    app = App.objects.create(app_key="ops1-missing-rule", name="OPS1 Missing Rule")
    _ = _ready_catalog(app, group_key="admin", requestable=True, approval_rule=False)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: requestable AuthorizationGroup 缺少 active ApprovalRule 会成为 blocking。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert [issue.code for issue in readiness.issues] == [
        "requestable_authorization_group_approval_rule_missing",
    ]
    assert readiness.issues[0].subject == "admin"


def test_ops1_configuration_readiness_is_ready_when_required_configuration_exists() -> None:
    # Given: active App 具备 owner、active Permission、AuthorizationGroup、ApprovalRule 和凭据。
    app = App.objects.create(app_key="ops1-ready", name="OPS1 Ready")
    _ = _ready_catalog(app, group_key="auditor", requestable=True, approval_rule=True)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 配置完整性返回 ready 且没有风险项。
    assert readiness.status == CONFIGURATION_STATUS_READY
    assert readiness.issues == ()


def test_ops1_configuration_readiness_blocks_managed_users_grant_without_policy() -> None:
    # Given: App 已满足基础发布要求, 但 MANAGED_USERS grant 没有 override 或 app default 策略。
    app = App.objects.create(app_key="ops1-managed-policy-missing", name="OPS1 Managed Missing")
    _ = _ready_managed_scope_catalog(app)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: MANAGED_USERS grant 缺少有效策略会阻止发布。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert [issue.code for issue in readiness.issues] == [
        "managed_scope_app_default_policy_missing",
    ]
    assert readiness.issues[0].severity == CONFIGURATION_STATUS_BLOCKING
    assert readiness.issues[0].subject == "admin:invoice.read:MANAGED_USERS"


def test_ops1_configuration_readiness_blocks_disabled_managed_scope_policy() -> None:
    # Given: MANAGED_USERS grant 只有 disabled override, 即使 app default 可用也不能继承。
    app = App.objects.create(app_key="ops1-managed-policy-disabled", name="OPS1 Managed Disabled")
    grant = _ready_managed_scope_catalog(app)
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="authorization_group_grant",
        authorization_group_grant=grant,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
        enabled=False,
    )

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: disabled 策略作为显式阻断项暴露。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert [issue.code for issue in readiness.issues] == ["managed_scope_policy_disabled"]
    assert readiness.issues[0].severity == CONFIGURATION_STATUS_BLOCKING
    assert readiness.issues[0].subject == "admin:invoice.read:MANAGED_USERS"


def test_ops1_configuration_readiness_warns_when_permission_supported_scopes_missing() -> None:
    # Given: App 已满足发布要求, 但存在 active Permission 缺少 supported_scopes。
    app = App.objects.create(app_key="ops1-warning", name="OPS1 Warning")
    _ = AppMembership.objects.create(app=app, user_id="owner-001", role="owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    auth_group = AuthorizationGroup.objects.create(
        app=app,
        key="operator",
        kind="role",
        name="Operator",
        requestable=True,
    )
    grouped_permission = Permission.objects.create(
        app=app,
        key="pipeline.run",
        name="Run pipeline",
        supported_scopes=["GLOBAL"],
    )
    group = PermissionGroup.objects.create(app=app, key="PIPELINE_GROUP", name="Pipeline")
    scope_missing_permission = Permission.objects.create(
        app=app,
        key="pipeline.audit",
        name="Audit pipeline",
        group=group,
        supported_scopes=[],
    )
    grouped_permission.group = group
    grouped_permission.save(update_fields=["group", "updated_at"])
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=auth_group,
        permission=grouped_permission,
        scope_key="GLOBAL",
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=auth_group,
        approver_userids=["manager-001"],
    )
    _ = AppCredentialService.create_static_token(app=app, name="OPS1 token")

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 缺少 supported_scopes 只产生 warning, 不阻止发布。
    assert readiness.status == CONFIGURATION_STATUS_WARNING
    assert [issue.code for issue in readiness.issues] == ["permission_supported_scopes_missing"]
    assert readiness.issues[0].severity == CONFIGURATION_STATUS_WARNING
    assert readiness.issues[0].subject == scope_missing_permission.key


def test_ops1_configuration_readiness_blocks_inactive_grant_targets() -> None:
    # Given: 授权组 grant 指向 inactive Permission。
    app = App.objects.create(app_key="ops1-inactive-grant-target", name="OPS1 Inactive Grant")
    _ = _ready_catalog(app, permission_active=False, approval_rule=True)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: readiness 暴露 grant 目标失效和缺少 active Permission。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert "authorization_group_grant_target_inactive" in {issue.code for issue in readiness.issues}


def test_ops1_configuration_readiness_warns_when_permission_group_inactive() -> None:
    # Given: active Permission 挂在 inactive PermissionGroup 下。
    app = App.objects.create(app_key="ops1-inactive-permission-group", name="OPS1 Inactive Group")
    permission_group = _ready_catalog(app, approval_rule=True)
    permission_group.is_active = False
    permission_group.save(update_fields=["is_active", "updated_at"])

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: inactive group 产生 warning。
    assert readiness.status == CONFIGURATION_STATUS_WARNING
    assert [issue.code for issue in readiness.issues] == ["permission_group_inactive"]


def _ready_catalog(
    app: App,
    *,
    group_key: str = "admin",
    requestable: bool = True,
    permission_active: bool = True,
    approval_rule: bool,
) -> PermissionGroup:
    _ = AppMembership.objects.create(app=app, user_id=f"{app.app_key}-owner", role="owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    permission_group = PermissionGroup.objects.create(app=app, key="CUSTOMER", name="Customer")
    permission = Permission.objects.create(
        app=app,
        group=permission_group,
        key="invoice.read",
        name="Read invoices",
        is_active=permission_active,
        supported_scopes=["GLOBAL"],
    )
    authorization_group = AuthorizationGroup.objects.create(
        app=app,
        key=group_key,
        kind="role",
        name=group_key,
        requestable=requestable,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=authorization_group,
        permission=permission,
        scope_key="GLOBAL",
    )
    if approval_rule:
        _ = ApprovalRule.objects.create(
            app=app,
            authorization_group=authorization_group,
            approver_userids=["manager-001"],
        )
    _ = AppCredentialService.create_static_token(app=app, name="OPS1 token")
    return permission_group


def _ready_managed_scope_catalog(app: App) -> AuthorizationGroupGrant:
    _ = AppMembership.objects.create(app=app, user_id=f"{app.app_key}-owner", role="owner")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下属")
    permission_group = PermissionGroup.objects.create(app=app, key="CUSTOMER", name="Customer")
    permission = Permission.objects.create(
        app=app,
        group=permission_group,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["MANAGED_USERS"],
    )
    authorization_group = AuthorizationGroup.objects.create(
        app=app,
        key="admin",
        kind="role",
        name="admin",
        requestable=True,
    )
    grant = AuthorizationGroupGrant.objects.create(
        authorization_group=authorization_group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=authorization_group,
        approver_userids=["manager-001"],
    )
    _ = AppCredentialService.create_static_token(app=app, name="OPS1 token")
    return grant

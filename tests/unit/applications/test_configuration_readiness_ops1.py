from __future__ import annotations

import pytest

from easyauth.applications.configuration import (
    CONFIGURATION_STATUS_BLOCKING,
    CONFIGURATION_STATUS_READY,
    CONFIGURATION_STATUS_WARNING,
    configuration_readiness_for_app,
)
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
    PermissionGroup,
)
from easyauth.applications.services import StaticTokenService

pytestmark = pytest.mark.django_db


def test_ops1_configuration_readiness_blocks_active_app_without_catalog_owner_or_credentials(
) -> None:
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


def test_ops1_configuration_readiness_blocks_requestable_authorization_group_without_rule() -> None:
    # Given: 可申请授权组已有 grant、凭据和 owner, 但没有 active ApprovalRule。
    app = App.objects.create(app_key="ops1-missing-rule", name="OPS1 Missing Rule")
    _ready_catalog(app, group_key="admin", requestable=True, approval_rule=False)

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
    _ready_catalog(app, group_key="auditor", requestable=True, approval_rule=True)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 配置完整性返回 ready 且没有风险项。
    assert readiness.status == CONFIGURATION_STATUS_READY
    assert readiness.issues == ()


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
    _ = StaticTokenService.create_token(app=app, name="OPS1 token")

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
    _ready_catalog(app, permission_active=False, approval_rule=True)

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: readiness 暴露 grant 目标失效和缺少 active Permission。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert "authorization_group_grant_target_inactive" in {
        issue.code for issue in readiness.issues
    }


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
    _ = StaticTokenService.create_token(app=app, name="OPS1 token")
    return permission_group

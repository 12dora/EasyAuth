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
    ApprovalRule,
    Permission,
    PermissionGroup,
    Role,
    RolePermission,
)
from easyauth.applications.services import StaticTokenService

pytestmark = pytest.mark.django_db


def test_ops1_configuration_readiness_blocks_active_app_without_roles_or_credentials() -> None:
    # Given: 一个 active App 还没有任何业务角色和可用凭据。
    app = App.objects.create(app_key="ops1-empty-app", name="OPS1 Empty App")

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 结果阻止发布, 并明确指出缺少 active Role 和 active 凭据。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert {issue.code for issue in readiness.issues} == {
        "active_role_missing",
        "active_credential_missing",
    }
    assert {issue.severity for issue in readiness.issues} == {CONFIGURATION_STATUS_BLOCKING}


def test_ops1_configuration_readiness_blocks_requestable_role_without_active_rule() -> None:
    # Given: 可申请角色已有权限和凭据, 但没有 active ApprovalRule。
    app = App.objects.create(app_key="ops1-missing-rule", name="OPS1 Missing Rule")
    role = Role.objects.create(app=app, key="admin", name="Admin", requestable=True)
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    _ = RolePermission.objects.create(role=role, permission=permission)
    _ = StaticTokenService.create_token(app=app, name="OPS1 token")

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: requestable Role 缺少 active ApprovalRule 会成为 blocking。
    assert readiness.status == CONFIGURATION_STATUS_BLOCKING
    assert [issue.code for issue in readiness.issues] == ["requestable_role_approval_rule_missing"]
    assert readiness.issues[0].subject == "admin"


def test_ops1_configuration_readiness_is_ready_when_required_configuration_exists() -> None:
    # Given: active App 具备 active Role、Permission、ApprovalRule 和 active 凭据。
    app = App.objects.create(app_key="ops1-ready", name="OPS1 Ready")
    role = Role.objects.create(app=app, key="auditor", name="Auditor", requestable=True)
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    _ = RolePermission.objects.create(role=role, permission=permission)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    _ = StaticTokenService.create_token(app=app, name="OPS1 token")

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 配置完整性返回 ready 且没有风险项。
    assert readiness.status == CONFIGURATION_STATUS_READY
    assert readiness.issues == ()


def test_ops1_configuration_readiness_warns_when_template_groups_leave_permission_unclassified(
) -> None:
    # Given: App 已满足发布要求, 但模板存在 group 且仍有 active Permission 未归类。
    app = App.objects.create(app_key="ops1-warning", name="OPS1 Warning")
    role = Role.objects.create(app=app, key="operator", name="Operator", requestable=True)
    grouped_permission = Permission.objects.create(app=app, key="pipeline.run", name="Run pipeline")
    ungrouped_permission = Permission.objects.create(
        app=app,
        key="pipeline.audit",
        name="Audit pipeline",
    )
    group = PermissionGroup.objects.create(app=app, key="PIPELINE_GROUP", name="Pipeline")
    grouped_permission.group = group
    grouped_permission.save(update_fields=["group", "updated_at"])
    _ = RolePermission.objects.create(role=role, permission=grouped_permission)
    _ = RolePermission.objects.create(role=role, permission=ungrouped_permission)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])
    _ = StaticTokenService.create_token(app=app, name="OPS1 token")

    # When: 应用负责人查看配置完整性。
    readiness = configuration_readiness_for_app(app)

    # Then: 未归类 Permission 只产生 warning, 不阻止发布。
    assert readiness.status == CONFIGURATION_STATUS_WARNING
    assert [issue.code for issue in readiness.issues] == ["permission_group_missing"]
    assert readiness.issues[0].severity == CONFIGURATION_STATUS_WARNING
    assert readiness.issues[0].subject == "pipeline.audit"

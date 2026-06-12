from __future__ import annotations

from pathlib import Path

import pytest
from django.core.exceptions import ValidationError

from easyauth.applications.models import (
    App,
    ApprovalRule,
    Permission,
    PermissionGroup,
    Role,
    RoleAccessPolicy,
    RolePermission,
)

pytestmark = pytest.mark.django_db


def test_application_model_modules_do_not_import_submodules_through_package_entrypoint() -> None:
    project_root = Path(__file__).resolve().parents[3]
    model_sources = (
        project_root / "src/easyauth/applications/models.py",
        project_root / "src/easyauth/applications/ops_models.py",
    )

    for source_path in model_sources:
        source = source_path.read_text()
        assert "from easyauth.applications import " not in source


def test_app_key_is_unique_when_duplicate_app_is_cleaned() -> None:
    # Given
    _ = App.objects.create(app_key="crm", name="CRM")
    duplicate = App(app_key="crm", name="CRM duplicate")

    # When / Then
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_role_key_is_unique_within_same_app_when_duplicate_role_is_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    _ = Role.objects.create(app=app, key="admin", name="Admin")
    duplicate = Role(app=app, key="admin", name="Admin duplicate")

    # When / Then
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_role_key_can_repeat_across_apps_when_role_is_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm", name="CRM")
    erp = App.objects.create(app_key="erp", name="ERP")
    _ = Role.objects.create(app=crm, key="admin", name="Admin")
    cross_app_role = Role(app=erp, key="admin", name="Admin")

    # When
    cross_app_role.full_clean()

    # Then
    assert cross_app_role.key == "admin"


def test_permission_key_is_unique_within_same_app_when_duplicate_permission_is_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    _ = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    duplicate = Permission(app=app, key="invoice.read", name="Read invoices duplicate")

    # When / Then
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_permission_key_can_repeat_across_apps_when_permission_is_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm", name="CRM")
    erp = App.objects.create(app_key="erp", name="ERP")
    _ = Permission.objects.create(app=crm, key="invoice.read", name="Read invoices")
    cross_app_permission = Permission(app=erp, key="invoice.read", name="Read invoices")

    # When
    cross_app_permission.full_clean()

    # Then
    assert cross_app_permission.key == "invoice.read"


def test_role_permission_rejects_cross_app_links_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm", name="CRM")
    erp = App.objects.create(app_key="erp", name="ERP")
    role = Role.objects.create(app=crm, key="admin", name="Admin")
    permission = Permission.objects.create(app=erp, key="invoice.read", name="Read invoices")
    role_permission = RolePermission(role=role, permission=permission)

    # When / Then
    with pytest.raises(ValidationError):
        role_permission.full_clean()


def test_approval_rule_requires_exactly_one_target_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="Admin")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    no_target_rule = ApprovalRule(app=app, approver_userids=["manager-001"])
    double_target_rule = ApprovalRule(
        app=app,
        role=role,
        permission=permission,
        approver_userids=["manager-001"],
    )

    # When / Then
    with pytest.raises(ValidationError):
        no_target_rule.full_clean()
    with pytest.raises(ValidationError):
        double_target_rule.full_clean()


def test_approval_rule_reports_target_field_errors_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="Admin")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    no_target_rule = ApprovalRule(app=app, approver_userids=["manager-001"])
    double_target_rule = ApprovalRule(
        app=app,
        role=role,
        permission=permission,
        approver_userids=["manager-001"],
    )

    # When / Then
    with pytest.raises(ValidationError) as no_target_error:
        no_target_rule.clean()
    assert no_target_error.value.message_dict == {
        "role": ["Approval rule must target exactly one role or permission."],
        "permission": ["Approval rule must target exactly one role or permission."],
    }

    with pytest.raises(ValidationError) as double_target_error:
        double_target_rule.clean()
    assert double_target_error.value.message_dict == {
        "role": ["Approval rule must target exactly one role or permission."],
        "permission": ["Approval rule must target exactly one role or permission."],
    }


def test_approval_rule_rejects_cross_app_target_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm", name="CRM")
    erp = App.objects.create(app_key="erp", name="ERP")
    cross_app_role = Role.objects.create(app=erp, key="admin", name="Admin")
    cross_app_permission = Permission.objects.create(
        app=erp,
        key="invoice.read",
        name="Read invoices",
    )
    role_rule = ApprovalRule(
        app=crm,
        role=cross_app_role,
        approver_userids=["manager-001"],
    )
    permission_rule = ApprovalRule(
        app=crm,
        permission=cross_app_permission,
        approver_userids=["manager-001"],
    )

    # When / Then
    with pytest.raises(ValidationError) as role_error:
        role_rule.clean()
    assert role_error.value.message_dict == {
        "role": ["Role must belong to the approval rule app."],
    }

    with pytest.raises(ValidationError) as permission_error:
        permission_rule.clean()
    assert permission_error.value.message_dict == {
        "permission": ["Permission must belong to the approval rule app."],
    }


def test_approval_rule_requires_dingtalk_approver_userids_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="Admin")
    empty_approvers_rule = ApprovalRule(app=app, role=role, approver_userids=[])

    # When / Then
    with pytest.raises(ValidationError):
        empty_approvers_rule.full_clean()


@pytest.mark.parametrize(
    "approver_userids",
    [
        [],
        ["manager-001", ""],
        ["manager-001", 123],
        "manager-001",
    ],
)
def test_approval_rule_reports_approver_userids_shape_error_when_cleaned(
    approver_userids: object,
) -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="Admin")
    rule = ApprovalRule(app=app, role=role, approver_userids=approver_userids)

    # When / Then
    with pytest.raises(ValidationError) as error:
        rule.clean()
    assert error.value.message_dict == {
        "approver_userids": ["DingTalk approver userids must be a non-empty list."],
    }


def test_permission_group_rejects_cross_app_parent_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm", name="CRM")
    erp = App.objects.create(app_key="erp", name="ERP")
    parent = PermissionGroup.objects.create(app=erp, key="ROOT", name="Root")
    group = PermissionGroup(app=crm, key="CHILD", name="Child", parent=parent, depth=2)

    # When / Then
    with pytest.raises(ValidationError) as error:
        group.clean()
    assert error.value.message_dict == {
        "parent": ["Permission group parent must belong to the same app."],
    }


def test_permission_group_rejects_parent_cycle_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    root = PermissionGroup.objects.create(app=app, key="ROOT", name="Root")
    child = PermissionGroup.objects.create(
        app=app,
        key="CHILD",
        name="Child",
        parent=root,
        depth=2,
    )
    root.parent = child
    root.depth = 3

    # When / Then
    with pytest.raises(ValidationError) as error:
        root.clean()
    assert error.value.message_dict == {
        "parent": ["Permission group tree cannot contain cycles."],
    }


def test_permission_group_rejects_depth_mismatch_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    parent = PermissionGroup.objects.create(app=app, key="ROOT", name="Root")
    group = PermissionGroup(app=app, key="CHILD", name="Child", parent=parent, depth=3)

    # When / Then
    with pytest.raises(ValidationError) as error:
        group.clean()
    assert error.value.message_dict == {
        "depth": ["Permission group depth must match its parent."],
    }


def test_permission_group_rejects_depth_above_max_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    group = PermissionGroup(app=app, key="ROOT", name="Root", depth=6)

    # When / Then
    with pytest.raises(ValidationError) as error:
        group.clean()
    assert error.value.message_dict == {
        "depth": ["Permission group depth cannot exceed 5."],
    }


def test_role_access_policy_requires_max_duration_for_high_risk_roles_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="Admin")
    policy = RoleAccessPolicy(role=role, is_high_risk=True, max_grant_duration_days=None)

    # When / Then
    with pytest.raises(ValidationError) as error:
        policy.clean()
    assert error.value.message_dict == {
        "max_grant_duration_days": ["High-risk roles need a max duration."],
    }


def test_role_access_policy_rejects_max_duration_for_normal_roles_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    role = Role.objects.create(app=app, key="viewer", name="Viewer")
    policy = RoleAccessPolicy(role=role, is_high_risk=False, max_grant_duration_days=7)

    # When / Then
    with pytest.raises(ValidationError) as error:
        policy.clean()
    assert error.value.message_dict == {
        "max_grant_duration_days": ["Only high-risk roles may set max duration."],
    }

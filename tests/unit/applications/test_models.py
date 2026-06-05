from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from easyauth.applications.models import (
    App,
    ApprovalRule,
    Permission,
    Role,
    RolePermission,
)

pytestmark = pytest.mark.django_db


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


def test_approval_rule_requires_dingtalk_approver_userids_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm", name="CRM")
    role = Role.objects.create(app=app, key="admin", name="Admin")
    empty_approvers_rule = ApprovalRule(app=app, role=role, approver_userids=[])

    # When / Then
    with pytest.raises(ValidationError):
        empty_approvers_rule.full_clean()

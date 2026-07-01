from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.access_requests.target_validation import (
    AccessRequestTargetValidationError,
    permission_target_errors,
    role_target_errors,
    validate_request_targets,
)
from easyauth.applications.models import App, ApprovalRule, Permission, Role

pytestmark = pytest.mark.django_db


def test_role_target_errors_returns_cross_app_role_errors_in_message_order() -> None:
    app = App.objects.create(app_key="target-role-cross-app", name="Target App")
    other_app = App.objects.create(app_key="target-role-cross-app-other", name="Other App")
    role = Role.objects.create(app=other_app, key="admin", name="Admin")
    _ = ApprovalRule.objects.create(app=other_app, role=role, approver_userids=["manager-001"])

    errors = role_target_errors(app, (role,))

    assert errors == (
        "admin: Role must belong to the access request app.",
        "admin: Role must have an active approval rule.",
    )


def test_role_target_errors_returns_inactive_role_error() -> None:
    app = App.objects.create(app_key="target-role-inactive", name="Target App")
    role = Role.objects.create(app=app, key="admin", name="Admin", is_active=False)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])

    errors = role_target_errors(app, (role,))

    assert errors == ("admin: Role must be active.",)


def test_role_target_errors_returns_non_requestable_role_error() -> None:
    app = App.objects.create(app_key="target-role-not-requestable", name="Target App")
    role = Role.objects.create(app=app, key="admin", name="Admin", requestable=False)
    _ = ApprovalRule.objects.create(app=app, role=role, approver_userids=["manager-001"])

    errors = role_target_errors(app, (role,))

    assert errors == ("admin: Role must be requestable.",)


def test_permission_target_errors_returns_cross_app_permission_errors_in_message_order() -> None:
    app = App.objects.create(app_key="target-permission-cross-app", name="Target App")
    other_app = App.objects.create(
        app_key="target-permission-cross-app-other",
        name="Other App",
    )
    permission = Permission.objects.create(
        app=other_app,
        key="invoice.read",
        name="Read invoices",
    )
    _ = ApprovalRule.objects.create(
        app=other_app,
        permission=permission,
        approver_userids=["manager-001"],
    )

    errors = permission_target_errors(app, (permission,))

    assert errors == (
        "invoice.read: Permission must belong to the access request app.",
        "invoice.read: Permission must have an active approval rule.",
    )


def test_permission_target_errors_returns_inactive_permission_error() -> None:
    app = App.objects.create(app_key="target-permission-inactive", name="Target App")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        is_active=False,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        permission=permission,
        approver_userids=["manager-001"],
    )

    errors = permission_target_errors(app, (permission,))

    assert errors == ("invoice.read: Permission must be active.",)


def test_permission_target_errors_returns_deprecated_permission_error() -> None:
    app = App.objects.create(app_key="target-permission-deprecated", name="Target App")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        deprecated_at=timezone.now(),
    )
    _ = ApprovalRule.objects.create(
        app=app,
        permission=permission,
        approver_userids=["manager-001"],
    )

    errors = permission_target_errors(app, (permission,))

    assert errors == ("invoice.read: Permission must not be deprecated.",)


def test_permission_target_errors_returns_direct_permission_without_active_rule_error() -> None:
    app = App.objects.create(app_key="target-permission-no-rule", name="Target App")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")

    errors = permission_target_errors(app, (permission,))

    assert errors == ("invoice.read: Permission must have an active approval rule.",)


def test_validate_request_targets_raises_role_errors_before_permission_errors() -> None:
    app = App.objects.create(app_key="target-validation-order", name="Target App")
    other_app = App.objects.create(app_key="target-validation-order-other", name="Other App")
    inactive_role = Role.objects.create(app=app, key="admin", name="Admin", is_active=False)
    non_requestable_role = Role.objects.create(
        app=app,
        key="auditor",
        name="Auditor",
        requestable=False,
    )
    cross_app_permission = Permission.objects.create(
        app=other_app,
        key="invoice.read",
        name="Read invoices",
    )
    inactive_permission = Permission.objects.create(
        app=app,
        key="invoice.write",
        name="Write invoices",
        is_active=False,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        role=inactive_role,
        approver_userids=["manager-001"],
    )
    _ = ApprovalRule.objects.create(
        app=app,
        role=non_requestable_role,
        approver_userids=["manager-001"],
    )
    _ = ApprovalRule.objects.create(
        app=other_app,
        permission=cross_app_permission,
        approver_userids=["manager-001"],
    )
    _ = ApprovalRule.objects.create(
        app=app,
        permission=inactive_permission,
        approver_userids=["manager-001"],
    )

    with pytest.raises(AccessRequestTargetValidationError) as exc_info:
        validate_request_targets(
            app,
            (inactive_role, non_requestable_role),
            (cross_app_permission, inactive_permission),
        )

    assert exc_info.value.messages == (
        "admin: Role must be active.",
        "auditor: Role must be requestable.",
        "invoice.read: Permission must belong to the access request app.",
        "invoice.read: Permission must have an active approval rule.",
        "invoice.write: Permission must be active.",
    )

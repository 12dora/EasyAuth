from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
from easyauth.access_requests.target_validation import (
    AccessRequestTargetValidationError,
    authorization_group_target_errors,
    direct_grant_target_errors,
    overlapping_target_errors,
    validate_request_targets,
)
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)

pytestmark = pytest.mark.django_db


def test_authorization_group_target_errors_returns_cross_app_group_error() -> None:
    app = App.objects.create(app_key="target-group-cross-app", name="Target App")
    other_app = App.objects.create(app_key="target-group-cross-app-other", name="Other App")
    group = AuthorizationGroup.objects.create(
        app=other_app,
        key="admin",
        kind="role",
        name="Admin",
    )

    errors = authorization_group_target_errors(app, (group,))

    assert errors == ("admin: Authorization group must belong to the access request app.",)


def test_authorization_group_target_errors_returns_inactive_group_error() -> None:
    app = App.objects.create(app_key="target-group-inactive", name="Target App")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="admin",
        kind="role",
        name="Admin",
        is_active=False,
    )

    errors = authorization_group_target_errors(app, (group,))

    assert errors == ("admin: Authorization group must be active.",)


def test_authorization_group_target_errors_returns_non_requestable_group_error() -> None:
    app = App.objects.create(app_key="target-group-not-requestable", name="Target App")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="admin",
        kind="role",
        name="Admin",
        requestable=False,
    )

    errors = authorization_group_target_errors(app, (group,))

    assert errors == ("admin: Authorization group must be requestable.",)


def test_direct_grant_target_errors_validates_permission_and_scope() -> None:
    app = App.objects.create(app_key="target-direct-grant-invalid", name="Target App")
    _ = AppScope.objects.create(app=app, key="SELF", name="本人")
    inactive_scope = AppScope.objects.create(app=app, key="TEAM", name="团队", is_active=False)
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["SELF", inactive_scope.key],
    )

    errors = direct_grant_target_errors(
        app,
        (ScopedAccessRequestGrant(permission=permission, scope_key=inactive_scope.key),),
    )

    assert errors == (
        "invoice.read:TEAM: Scope must belong to the access request app and be active.",
    )


def test_direct_grant_target_errors_returns_deprecated_permission_error() -> None:
    app = App.objects.create(app_key="target-direct-grant-deprecated", name="Target App")
    _ = AppScope.objects.create(app=app, key="SELF", name="本人")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["SELF"],
        deprecated_at=timezone.now(),
    )

    errors = direct_grant_target_errors(
        app,
        (ScopedAccessRequestGrant(permission=permission, scope_key="SELF"),),
    )

    assert errors == ("invoice.read:SELF: Permission must not be deprecated.",)


def test_direct_grant_target_errors_allows_permission_without_approval_rule() -> None:
    app = App.objects.create(app_key="target-direct-grant-no-rule", name="Target App")
    _ = AppScope.objects.create(app=app, key="SELF", name="本人")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["SELF"],
    )

    errors = direct_grant_target_errors(
        app,
        (ScopedAccessRequestGrant(permission=permission, scope_key="SELF"),),
    )

    assert errors == ()


def test_overlapping_target_errors_rejects_same_permission_and_scope() -> None:
    app = App.objects.create(app_key="target-overlap", name="Target App")
    _ = AppScope.objects.create(app=app, key="SELF", name="本人")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["SELF"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="Reader",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="SELF",
    )

    errors = overlapping_target_errors(
        (group,),
        (ScopedAccessRequestGrant(permission=permission, scope_key="SELF"),),
    )

    assert errors == (
        "invoice.read:SELF: Direct grant must not duplicate an active authorization group grant.",
    )


def test_overlapping_target_errors_allows_same_permission_on_different_scope() -> None:
    app = App.objects.create(app_key="target-distinct-scope", name="Target App")
    _ = AppScope.objects.create(app=app, key="SELF", name="本人")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下级用户")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["SELF", "MANAGED_USERS"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="Reader",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="SELF",
    )

    errors = overlapping_target_errors(
        (group,),
        (
            ScopedAccessRequestGrant(
                permission=permission,
                scope_key="MANAGED_USERS",
            ),
        ),
    )

    assert errors == ()


def test_validate_request_targets_raises_group_errors_before_direct_grant_errors() -> None:
    app = App.objects.create(app_key="target-validation-order", name="Target App")
    other_app = App.objects.create(app_key="target-validation-order-other", name="Other App")
    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="admin",
        kind="role",
        name="Admin",
        is_active=False,
    )
    cross_app_permission = Permission.objects.create(
        app=other_app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["GLOBAL"],
    )
    inactive_permission = Permission.objects.create(
        app=app,
        key="invoice.write",
        name="Write invoices",
        supported_scopes=["SELF"],
        is_active=False,
    )
    _ = AppScope.objects.create(app=app, key="SELF", name="本人")

    with pytest.raises(AccessRequestTargetValidationError) as exc_info:
        validate_request_targets(
            app,
            (inactive_group,),
            (
                ScopedAccessRequestGrant(permission=cross_app_permission, scope_key="GLOBAL"),
                ScopedAccessRequestGrant(permission=inactive_permission, scope_key="SELF"),
            ),
        )

    assert exc_info.value.messages == (
        "admin: Authorization group must be active.",
        "invoice.read:GLOBAL: Permission must belong to the access request app.",
        "invoice.read:GLOBAL: Scope must belong to the access request app and be active.",
        "invoice.write:SELF: Permission must be active.",
    )

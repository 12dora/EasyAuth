from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestPermission,
    AccessRequestRole,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, Permission, Role
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("request_type", ["grant", "change", "revoke", "renew"])
def test_request_type_accepts_supported_values_when_access_request_is_cleaned(
    request_type: str,
) -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id=f"user-{request_type}")
    app = App.objects.create(app_key=f"app-{request_type}", name=f"App {request_type}")
    access_request = AccessRequest(user=user, app=app, request_type=request_type)

    # When
    access_request.full_clean()

    # Then
    assert access_request.request_type == request_type


def test_request_type_rejects_unknown_value_when_access_request_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-unknown-request")
    app = App.objects.create(app_key="unknown-request-app", name="Unknown Request App")
    access_request = AccessRequest(user=user, app=app, request_type="unknown")

    # When / Then
    with pytest.raises(ValidationError):
        access_request.full_clean()


@pytest.mark.parametrize(
    "status",
    ["submitted", "approved", "rejected", "grant_applied", "grant_failed"],
)
def test_status_accepts_supported_values_when_access_request_is_cleaned(status: str) -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id=f"user-{status}")
    app = App.objects.create(app_key=f"app-{status}", name=f"App {status}")
    applied_at_by_status = {"grant_applied": timezone.now()}
    access_request = AccessRequest(
        user=user,
        app=app,
        status=status,
        applied_at=applied_at_by_status.get(status),
    )

    # When
    access_request.full_clean()

    # Then
    assert access_request.status == status


def test_status_rejects_unknown_value_when_access_request_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-unknown-status")
    app = App.objects.create(app_key="unknown-status-app", name="Unknown Status App")
    access_request = AccessRequest(user=user, app=app, status="unknown")

    # When / Then
    with pytest.raises(ValidationError):
        access_request.full_clean()


def test_approved_request_does_not_create_grant_when_saved() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-approved")
    app = App.objects.create(app_key="approved-app", name="Approved App")

    # When
    _ = AccessRequest.objects.create(user=user, app=app, status="approved")

    # Then
    assert AccessGrant.objects.count() == 0


def test_approved_request_rejects_applied_timestamp_when_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-approved-applied-at")
    app = App.objects.create(app_key="approved-applied-at-app", name="Approved Applied App")
    access_request = AccessRequest(
        user=user,
        app=app,
        status="approved",
        applied_at=timezone.now(),
    )

    # When / Then
    with pytest.raises(ValidationError):
        access_request.full_clean()


def test_grant_applied_request_requires_applied_timestamp_when_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-grant-applied-no-timestamp")
    app = App.objects.create(
        app_key="grant-applied-no-timestamp-app",
        name="Grant Applied App",
    )
    access_request = AccessRequest(user=user, app=app, status="grant_applied")

    # When / Then
    with pytest.raises(ValidationError):
        access_request.full_clean()


def test_access_request_role_rejects_cross_app_role_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-request-role", name="CRM")
    erp = App.objects.create(app_key="erp-request-role", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-request-role")
    access_request = AccessRequest.objects.create(user=user, app=crm)
    role = Role.objects.create(app=erp, key="admin", name="Admin")
    request_role = AccessRequestRole(access_request=access_request, role=role)

    # When / Then
    with pytest.raises(ValidationError):
        request_role.full_clean()


def test_access_request_permission_rejects_cross_app_permission_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-request-permission", name="CRM")
    erp = App.objects.create(app_key="erp-request-permission", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-request-permission")
    access_request = AccessRequest.objects.create(user=user, app=crm)
    permission = Permission.objects.create(app=erp, key="invoice.read", name="Read invoices")
    request_permission = AccessRequestPermission(
        access_request=access_request, permission=permission
    )

    # When / Then
    with pytest.raises(ValidationError):
        request_permission.full_clean()

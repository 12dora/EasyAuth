from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.grants.models import AccessGrant

pytestmark = pytest.mark.django_db

VALID_PAYLOAD_DIGEST = "a" * 64


@pytest.mark.parametrize("request_type", ["grant", "change", "revoke", "renew"])
def test_request_type_accepts_supported_values_when_access_request_is_cleaned(
    request_type: str,
) -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id=f"user-{request_type}")
    app = App.objects.create(app_key=f"app-{request_type}", name=f"App {request_type}")
    access_request = AccessRequest(
        user=user,
        app=app,
        request_type=request_type,
        idempotency_key=f"request-type-{request_type}",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )

    # When
    access_request.full_clean()

    # Then
    assert access_request.request_type == request_type


def test_request_type_rejects_unknown_value_when_access_request_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-unknown-request")
    app = App.objects.create(app_key="unknown-request-app", name="Unknown Request App")
    access_request = AccessRequest(
        user=user,
        app=app,
        request_type="unknown",
        idempotency_key="request-type-unknown",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )

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
        idempotency_key=f"request-status-{status}",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )

    # When
    access_request.full_clean()

    # Then
    assert access_request.status == status


def test_status_rejects_unknown_value_when_access_request_is_cleaned() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-unknown-status")
    app = App.objects.create(app_key="unknown-status-app", name="Unknown Status App")
    access_request = AccessRequest(
        user=user,
        app=app,
        status="unknown",
        idempotency_key="request-status-unknown",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )

    # When / Then
    with pytest.raises(ValidationError):
        access_request.full_clean()


def test_approved_request_does_not_create_grant_when_saved() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="user-approved")
    app = App.objects.create(app_key="approved-app", name="Approved App")

    # When
    _ = AccessRequest.objects.create(
        user=user,
        app=app,
        status="approved",
        idempotency_key="approved-without-grant",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )

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
        idempotency_key="approved-with-applied-at",
        payload_digest=VALID_PAYLOAD_DIGEST,
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
    access_request = AccessRequest(
        user=user,
        app=app,
        status="grant_applied",
        idempotency_key="grant-applied-without-timestamp",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )

    # When / Then
    with pytest.raises(ValidationError):
        access_request.full_clean()


def test_access_request_group_rejects_cross_app_authorization_group_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-request-group", name="CRM")
    erp = App.objects.create(app_key="erp-request-group", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-request-group")
    access_request = AccessRequest.objects.create(
        user=user,
        app=crm,
        idempotency_key="cross-app-group",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )
    authorization_group = AuthorizationGroup.objects.create(
        app=erp,
        key="admin",
        kind="role",
        name="Admin",
    )
    request_group = AccessRequestGroup(
        access_request=access_request,
        authorization_group=authorization_group,
    )

    # When / Then
    with pytest.raises(ValidationError):
        request_group.full_clean()


def test_access_request_permission_rejects_cross_app_permission_when_cleaned() -> None:
    # Given
    crm = App.objects.create(app_key="crm-request-permission", name="CRM")
    erp = App.objects.create(app_key="erp-request-permission", name="ERP")
    user = UserMirror.objects.create(authentik_user_id="user-request-permission")
    access_request = AccessRequest.objects.create(
        user=user,
        app=crm,
        idempotency_key="cross-app-permission",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )
    permission = Permission.objects.create(app=erp, key="invoice.read", name="Read invoices")
    request_permission = AccessRequestPermission(
        access_request=access_request, permission=permission
    )

    # When / Then
    with pytest.raises(ValidationError):
        request_permission.full_clean()


def test_access_request_permission_allows_same_permission_on_distinct_scopes_when_saved() -> None:
    # Given
    app = App.objects.create(app_key="crm-request-permission-scopes", name="CRM")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    _ = AppScope.objects.create(app=app, key="REGION_CN", name="Region CN")
    user = UserMirror.objects.create(authentik_user_id="user-request-permission-scopes")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        idempotency_key="distinct-scopes",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["GLOBAL", "REGION_CN"],
    )

    # When
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=permission,
        scope_key="GLOBAL",
    )
    _ = AccessRequestPermission.objects.create(
        access_request=access_request,
        permission=permission,
        scope_key="REGION_CN",
    )
    duplicate = AccessRequestPermission(
        access_request=access_request,
        permission=permission,
        scope_key="GLOBAL",
    )
    expected_permission_targets = 2

    # Then
    assert AccessRequestPermission.objects.count() == expected_permission_targets
    with pytest.raises(ValidationError):
        duplicate.full_clean()


def test_access_request_permission_rejects_unsupported_scope_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm-request-permission-unsupported-scope", name="CRM")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    _ = AppScope.objects.create(app=app, key="REGION_CN", name="Region CN")
    user = UserMirror.objects.create(authentik_user_id="user-request-permission-unsupported-scope")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        idempotency_key="unsupported-scope",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["GLOBAL"],
    )
    request_permission = AccessRequestPermission(
        access_request=access_request,
        permission=permission,
        scope_key="REGION_CN",
    )

    # When / Then
    with pytest.raises(ValidationError) as error:
        request_permission.full_clean()
    assert error.value.message_dict == {
        "scope_key": ["Scope key must be supported by the permission."],
    }


def test_access_request_permission_rejects_missing_scope_when_cleaned() -> None:
    # Given
    app = App.objects.create(app_key="crm-request-permission-missing-scope", name="CRM")
    user = UserMirror.objects.create(authentik_user_id="user-request-permission-missing-scope")
    access_request = AccessRequest.objects.create(
        user=user,
        app=app,
        idempotency_key="missing-scope",
        payload_digest=VALID_PAYLOAD_DIGEST,
    )
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Read invoices",
        supported_scopes=["GLOBAL"],
    )
    request_permission = AccessRequestPermission(
        access_request=access_request,
        permission=permission,
        scope_key="GLOBAL",
    )

    # When / Then
    with pytest.raises(ValidationError) as error:
        request_permission.full_clean()
    assert error.value.message_dict == {
        "scope_key": ["Scope key must reference an app scope."],
    }

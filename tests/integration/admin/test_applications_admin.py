from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

import pytest
from django.contrib import admin as django_admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory
from django.urls import reverse

from easyauth.applications.admin import (
    AppCredentialAdmin,
    ApprovalRuleAdmin,
)
from easyauth.applications.models import (
    App,
    AppCredential,
    ApprovalRule,
    AuthorizationGroup,
    Permission,
)
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from django.http import HttpRequest

pytestmark = pytest.mark.django_db

ADMIN_LOGIN_VALUE: Final = "admin-surface-login"


def test_application_models_are_registered_in_admin() -> None:
    # Given / When / Then
    assert django_admin.site.is_registered(App) is True
    assert django_admin.site.is_registered(Permission) is True
    assert django_admin.site.is_registered(ApprovalRule) is True
    assert django_admin.site.is_registered(AppCredential) is True


def test_admin_index_is_reachable_for_superuser() -> None:
    # Given
    client = _authenticated_admin_client("admin-surface")

    # When
    response = client.get("/admin/")

    # Then
    assert response.status_code == HTTPStatus.OK


def test_app_admin_changelist_page_is_reachable_for_superuser() -> None:
    # Given
    client = _authenticated_admin_client("admin-app-page")

    # When
    response = client.get(reverse("admin:applications_app_changelist"))

    # Then
    assert response.status_code == HTTPStatus.OK


def test_approval_rule_admin_add_page_is_reachable_for_superuser() -> None:
    # Given
    client = _authenticated_admin_client("admin-approval-rule-page")

    # When
    response = client.get(reverse("admin:applications_approvalrule_add"))

    # Then
    assert response.status_code == HTTPStatus.OK


def test_app_credential_admin_view_page_does_not_disclose_token_or_allow_save() -> None:
    # Given
    client = _authenticated_admin_client("admin-credential-view")
    app = App.objects.create(app_key="crm-credential-page", name="CRM Credential Page")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")
    credential = AppCredential.objects.get(id=issue.credential_id)

    # When
    response = client.get(
        reverse("admin:applications_appcredential_change", args=[credential.id]),
    )

    # Then
    assert response.status_code == HTTPStatus.OK
    assert b"token_hash" not in response.content
    assert issue.plaintext_token.encode() not in response.content
    assert b'name="_save"' not in response.content


def test_app_credential_admin_hides_token_hash_from_list_and_form() -> None:
    # Given
    request = _request()
    credential_admin = AppCredentialAdmin(AppCredential, AdminSite())

    # When
    list_display = credential_admin.get_list_display(request)
    form_class = credential_admin.get_form(request)
    search_fields = credential_admin.get_search_fields(request)

    # Then
    assert "token_hash" not in list_display
    assert "token_hash" not in form_class.base_fields
    assert "token_hash" not in search_fields


def test_app_credential_admin_does_not_allow_direct_existing_credential_mutation() -> None:
    # Given
    request = _request_for_superuser("credential-admin-viewer")
    app = App.objects.create(app_key="crm-credential-admin", name="CRM Credential Admin")
    issue = StaticTokenService.create_token(app=app, name="CRM integration")
    credential = AppCredential.objects.get(id=issue.credential_id)
    credential_admin = AppCredentialAdmin(AppCredential, AdminSite())

    # When
    form_class = credential_admin.get_form(request, obj=credential)

    # Then
    assert form_class.base_fields == {}
    assert credential_admin.has_change_permission(request, credential) is False
    assert credential_admin.has_delete_permission(request, credential) is False
    assert credential_admin.has_view_permission(request, credential) is True


def test_approval_rule_admin_rejects_authorization_group_from_another_app() -> None:
    # Given
    crm = App.objects.create(app_key="crm-admin-rule", name="CRM Admin Rule")
    erp = App.objects.create(app_key="erp-admin-rule", name="ERP Admin Rule")
    cross_app_group = AuthorizationGroup.objects.create(
        app=erp,
        key="admin",
        kind="role",
        name="Admin",
    )
    rule_admin = ApprovalRuleAdmin(ApprovalRule, AdminSite())
    form_class = rule_admin.get_form(_request())

    # When
    form = form_class(
        data={
            "app": str(crm.id),
            "authorization_group": str(cross_app_group.id),
            "permission": "",
            "approver_userids": '["manager-001"]',
            "is_active": "on",
        },
    )

    # Then
    assert form.is_valid() is False
    assert "Authorization group must belong to the approval rule app." in str(form.errors)


def _request() -> HttpRequest:
    return RequestFactory().get("/admin/")


def _authenticated_admin_client(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=ADMIN_LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=ADMIN_LOGIN_VALUE) is True
    return client


def _request_for_superuser(username: str) -> HttpRequest:
    request = _request()
    request.user = User.objects.create_superuser(username=username, password=ADMIN_LOGIN_VALUE)
    return request


def test_permission_admin_change_bumps_catalog_version_and_writes_audit() -> None:
    # Given: 目录里有一个 active Permission, 下游快照锚定当前 catalog_version。
    client = _authenticated_admin_client("admin-catalog-bump")
    app = App.objects.create(app_key="admin-bump-app", name="Bump App")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="Invoice Read",
        supported_scopes=["GLOBAL"],
    )
    original_version = app.catalog_version

    # When: 超管在 /admin/ 停用该 Permission。
    response = client.post(
        reverse("admin:applications_permission_change", args=[permission.id]),
        data={
            "app": str(app.id),
            "key": permission.key,
            "name": permission.name,
            "description": "",
            "supported_scopes": '["GLOBAL"]',
            "risk_level": "standard",
            "deprecated_reason": "",
        },
        follow=True,
    )

    # Then: catalog_version 递增且写入审计, 下游快照能识别本次撤销。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert app.catalog_version == original_version + 1
    audit_log = AuditLog.objects.get(event_type="app_catalog_version_bumped")
    assert audit_log.metadata["reason"] == "django_admin_updated"
    assert audit_log.metadata["model"] == "Permission"

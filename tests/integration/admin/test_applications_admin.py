from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final

import pytest
from django.contrib import admin as django_admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory

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
from easyauth.applications.services import AppCredentialService

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


def test_admin_route_is_not_registered() -> None:
    # Given: Django staff/superuser session 不再形成产品特权入口。
    client = Client(HTTP_HOST="localhost")

    # When
    response = client.get("/admin/")

    # Then: 平行 `/admin/` 特权面不可达。
    assert response.status_code == HTTPStatus.NOT_FOUND


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
    issue = AppCredentialService.create_static_token(app=app, name="CRM integration")
    credential = AppCredential.objects.get(id=issue.credential.id)
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


def _request_for_superuser(username: str) -> HttpRequest:
    request = _request()
    request.user = User.objects.create_superuser(username=username, password=ADMIN_LOGIN_VALUE)
    return request

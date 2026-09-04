from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestApprover,
    AccessRequestGroup,
)
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    Permission,
)
from easyauth.grants.models import AccessGrant, AccessGrantPermission
from tests.integration.portal.helpers import logged_in_client
from tests.integration.portal.json_helpers import json_object

pytestmark = pytest.mark.django_db

REQUEST_CATALOG_URL: Final = "/portal/api/v1/request-catalog"
GRANTS_API_URL: Final = "/portal/api/v1/me/grants"
EXPIRING_API_URL: Final = "/portal/api/v1/me/grants/expiring"
REQUESTS_API_URL: Final = "/portal/api/v1/me/access-requests"
APPROVALS_API_URL: Final = "/portal/api/v1/me/approvals"
ALIAS: Final = "海关数据"


def test_request_catalog_emits_app_alias() -> None:
    client, _user = logged_in_client("catalog-alias-user")
    app = App.objects.create(
        app_key="catalog-alias-crm",
        name="EasyCustoms",
        alias=ALIAS,
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="auditor",
        kind="role",
        name="审计员",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=["manager-001"],
    )

    response = client.get(REQUEST_CATALOG_URL)

    payload = json_object(response)
    assert response.status_code == HTTPStatus.OK
    apps = payload["apps"]
    assert isinstance(apps, list)
    item = apps[0]
    assert isinstance(item, dict)
    assert item["name"] == "EasyCustoms"
    assert item["alias"] == ALIAS


def test_my_grants_and_expiring_emit_app_alias() -> None:
    client, user = logged_in_client("grants-alias-user")
    app = App.objects.create(app_key="grants-alias-crm", name="EasyCustoms", alias=ALIAS)
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    permission = Permission.objects.create(
        app=app,
        key="customs.read",
        name="查看海关",
        supported_scopes=[scope.key],
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=scope.key,
    )

    grants = client.get(GRANTS_API_URL)
    expiring = client.get(EXPIRING_API_URL)

    assert grants.status_code == HTTPStatus.OK
    grant_items = json_object(grants)["data"]
    assert isinstance(grant_items, list)
    grant_item = grant_items[0]
    assert isinstance(grant_item, dict)
    assert grant_item["app_name"] == "EasyCustoms"
    assert grant_item["app_alias"] == ALIAS
    assert expiring.status_code == HTTPStatus.OK


def test_access_request_list_emits_app_alias() -> None:
    client, user = logged_in_client("requests-alias-user")
    app = App.objects.create(app_key="requests-alias-crm", name="EasyCustoms", alias=ALIAS)
    _ = AccessRequest.objects.create(
        user=user,
        app=app,
        reason="申请海关数据",
        idempotency_key="requests-alias-key",
        payload_digest="a" * 64,
    )

    response = client.get(REQUESTS_API_URL)

    items = json_object(response)["data"]
    assert response.status_code == HTTPStatus.OK
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["app_name"] == "EasyCustoms"
    assert item["app_alias"] == ALIAS


def test_approvals_list_emits_app_alias() -> None:
    client, approver = logged_in_client("approvals-alias-approver")
    applicant = UserMirror.objects.create(authentik_user_id="approvals-alias-applicant")
    app = App.objects.create(app_key="approvals-alias-crm", name="EasyCustoms", alias=ALIAS)
    group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="读者",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=group,
        approver_userids=[approver.authentik_user_id],
    )
    access_request = AccessRequest.objects.create(
        user=applicant,
        app=app,
        reason="审批别名",
        idempotency_key="approvals-alias-key",
        payload_digest="b" * 64,
    )
    _ = AccessRequestGroup.objects.create(
        access_request=access_request,
        authorization_group=group,
    )
    _ = AccessRequestApprover.objects.create(access_request=access_request, approver=approver)

    response = client.get(APPROVALS_API_URL)

    items = json_object(response)["data"]
    assert response.status_code == HTTPStatus.OK
    assert isinstance(items, list)
    item = items[0]
    assert isinstance(item, dict)
    assert item["app_name"] == "EasyCustoms"
    assert item["app_alias"] == ALIAS

from __future__ import annotations

from http import HTTPStatus
from typing import Final

import pytest
from django.test import Client

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    MEMBERSHIP_SOURCE_DEPARTMENT,
    MEMBERSHIP_SOURCE_USER,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
    DepartmentGrantPolicy,
)
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

pytestmark = pytest.mark.django_db

CURRENT_GRANT_URL: Final = "/console/api/v1/users/{user_id}/apps/{app_key}/current-grant"
ACCESS_GRANTS_URL: Final = "/console/api/v1/operations/access-grants"


def test_current_grant_requires_authentication() -> None:
    client = Client(HTTP_HOST="localhost")

    response = client.get(CURRENT_GRANT_URL.format(user_id="u", app_key="app"))

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_current_grant_returns_null_when_user_has_no_current_grant() -> None:
    client = _logged_in_superuser("current-grant-null-admin")
    user = UserMirror.objects.create(authentik_user_id="current-grant-null-user")
    app = App.objects.create(app_key="current-grant-null-app", name="CRM")

    response = client.get(
        CURRENT_GRANT_URL.format(user_id=user.authentik_user_id, app_key=app.app_key),
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"grant": None}


def test_current_grant_returns_404_for_unknown_user_or_app() -> None:
    client = _logged_in_superuser("current-grant-404-admin")
    user = UserMirror.objects.create(authentik_user_id="current-grant-404-user")
    app = App.objects.create(app_key="current-grant-404-app", name="CRM")

    unknown_user = client.get(
        CURRENT_GRANT_URL.format(user_id="missing-user", app_key=app.app_key),
    )
    unknown_app = client.get(
        CURRENT_GRANT_URL.format(user_id=user.authentik_user_id, app_key="missing-app"),
    )

    assert unknown_user.status_code == HTTPStatus.NOT_FOUND
    assert unknown_user.json()["error"]["code"] == "NOT_FOUND"
    assert unknown_user.json()["error"]["details"] == {"user_id": "missing-user"}
    assert unknown_app.status_code == HTTPStatus.NOT_FOUND
    assert unknown_app.json()["error"]["code"] == "NOT_FOUND"
    assert unknown_app.json()["error"]["details"] == {"app_key": "missing-app"}


def test_current_grant_includes_department_and_user_sources() -> None:
    client = _logged_in_superuser("current-grant-mixed-admin")
    user = UserMirror.objects.create(authentik_user_id="current-grant-mixed-user", name="混合用户")
    app, group, permission = _catalog("current-grant-mixed")
    policy = DepartmentGrantPolicy.objects.create(
        source_slug="dingtalk",
        corp_id="corp",
        dept_id="1",
        app=app,
        grant_type="permanent",
        reason="部门策略",
        created_by_type="admin",
        created_by_id="admin",
        updated_by_type="admin",
        updated_by_id="admin",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        source=MEMBERSHIP_SOURCE_USER,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
        department_policy=policy,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="GLOBAL",
        source=MEMBERSHIP_SOURCE_USER,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="GLOBAL",
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
        department_policy=policy,
    )

    response = client.get(
        CURRENT_GRANT_URL.format(user_id=user.authentik_user_id, app_key=app.app_key),
    )

    row = response.json()["grant"]
    assert response.status_code == HTTPStatus.OK
    assert row["id"] == grant.id
    assert row["user_name"] == "混合用户"
    assert {(item["key"], item["source"]) for item in row["authorization_groups"]} == {
        (group.key, MEMBERSHIP_SOURCE_USER),
        (group.key, MEMBERSHIP_SOURCE_DEPARTMENT),
    }
    assert {(item["permission"], item["source"]) for item in row["direct_grants"]} == {
        (permission.key, MEMBERSHIP_SOURCE_USER),
        (permission.key, MEMBERSHIP_SOURCE_DEPARTMENT),
    }


def test_current_grant_expands_current_version_not_historical() -> None:
    client = _logged_in_superuser("current-grant-history-admin")
    user = UserMirror.objects.create(authentik_user_id="current-grant-history-user")
    app = App.objects.create(app_key="current-grant-history-app", name="CRM", alias="客户")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    sales = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="销售")
    finance = AuthorizationGroup.objects.create(app=app, key="finance", kind="role", name="财务")
    read = Permission.objects.create(
        app=app,
        key="order.view",
        name="查看订单",
        supported_scopes=["GLOBAL"],
    )
    approve = Permission.objects.create(
        app=app,
        key="order.approve",
        name="审批订单",
        supported_scopes=["GLOBAL"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=sales,
        permission=read,
        scope_key="GLOBAL",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=finance,
        permission=approve,
        scope_key="GLOBAL",
    )
    historical = AccessGrant.objects.create(
        user=user,
        app=app,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
        version=1,
    )
    current = AccessGrant.objects.create(user=user, app=app, version=2)
    _ = AccessGrantGroup.objects.create(grant=historical, authorization_group=sales)
    _ = AccessGrantGroup.objects.create(grant=current, authorization_group=finance)

    current_response = client.get(
        CURRENT_GRANT_URL.format(user_id=user.authentik_user_id, app_key=app.app_key),
    )
    history_response = client.get(
        ACCESS_GRANTS_URL,
        {
            "app_key": app.app_key,
            "user_id": user.authentik_user_id,
            "current_only": "false",
            "current": "false",
        },
    )

    current_row = current_response.json()["grant"]
    historical_row = next(
        item for item in history_response.json()["data"] if item["id"] == historical.id
    )
    assert current_response.status_code == HTTPStatus.OK
    assert current_row["id"] == current.id
    assert current_row["version"] == 2
    assert current_row["authorization_groups"][0]["key"] == finance.key
    assert current_row["grants"][0]["permission"] == approve.key
    assert historical_row["version"] == 1
    assert historical_row["authorization_groups"][0]["key"] == sales.key
    assert historical_row["grants"][0]["permission"] == read.key
    assert historical_row["grants"][0]["source_type"] == "group"


def _catalog(prefix: str) -> tuple[App, AuthorizationGroup, Permission]:
    app = App.objects.create(app_key=f"{prefix}-app", name=prefix)
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    permission = Permission.objects.create(
        app=app,
        key="order.order.view",
        name="查看订单",
        supported_scopes=["GLOBAL"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="sales",
        kind="role",
        name="销售",
        requestable=False,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="GLOBAL",
    )
    return app, group, permission


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    authenticate_console_admin(client, username)
    return client

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol, cast

import pytest
from django.db import connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from pydantic import TypeAdapter

from easyauth.admin_console.authorization_groups_api import console_authorization_groups
from easyauth.admin_console.permission_catalog_data import authorization_groups_payload
from easyauth.api.errors import JsonValue
from easyauth.applications.models import (
    App,
    AppMembership,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
    PermissionGroup,
)
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

if TYPE_CHECKING:
    from django.conf import LazySettings
    from django.http import HttpRequest

pytestmark = pytest.mark.django_db

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)
AUTHORIZATION_GROUP_QUERY_COUNT_GROUPS: Final = 3
AUTHORIZATION_GROUP_PAYLOAD_MAX_QUERIES: Final = 8
AUTHORIZATION_GROUP_LARGE_DIRECTORY_SIZE: Final = 105
AUTHORIZATION_GROUP_PAGE_SIZE_UNDER_TEST: Final = 50


@pytest.fixture(autouse=True)
def _console_superuser_groups(settings: LazySettings) -> None:  # pyright: ignore[reportUnusedFunction]
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)


class HttpResponseLike(Protocol):
    @property
    def content(self) -> bytes: ...


def test_ops1_owner_reads_permission_tree_catalog_for_owned_app() -> None:
    client = _logged_in_user("ops1-catalog-owner")
    app = _member_app("ops1-catalog-tree", "ops1-catalog-owner", role="owner")
    group = PermissionGroup.objects.create(app=app, key="PIPELINE", name="Pipeline")
    child = PermissionGroup.objects.create(
        app=app,
        key="PIPELINE_BUILD",
        name="Build",
        parent=group,
        depth=2,
    )
    _ = Permission.objects.create(app=app, group=child, key="pipeline.run", name="Run pipeline")
    _ = Permission.objects.create(
        app=app,
        key="inactive.permission",
        name="Inactive",
        is_active=False,
    )

    response = client.get(_api_url(app.app_key, "permission-tree"))

    tree = _response_json_object(response)
    root_node = _json_object(_json_list(tree["groups"])[0])
    child_node = _json_object(_json_list(root_node["children"])[0])
    permission_node = _json_object(_json_list(child_node["children"])[0])
    assert response.status_code == HTTPStatus.OK
    assert tree["app_key"] == app.app_key
    assert _json_object(_json_list(child_node["permissions"])[0])["key"] == "pipeline.run"
    assert permission_node["type"] == "permission"
    assert permission_node["key"] == "pipeline.run"
    assert "inactive.permission" not in response.content.decode()


def test_ops1_superuser_reads_authorization_group_grant_managed_scope_policy() -> None:
    client = _logged_in_superuser("ops1-catalog-authz-read")
    app = App.objects.create(app_key="ops1-catalog-authz-read", name="Authz Read")
    scope = AppScope.objects.create(app=app, key="MANAGED_USERS", name="Managed users")
    direct_permission = Permission.objects.create(
        app=app,
        key="order.read",
        name="Read orders",
        supported_scopes=[scope.key],
    )
    inherited_permission = Permission.objects.create(
        app=app,
        key="order.audit",
        name="Audit orders",
        supported_scopes=[scope.key],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="manager",
        kind="role",
        name="Manager",
    )
    direct_grant = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=direct_permission,
        scope_key=scope.key,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=inherited_permission,
        scope_key=scope.key,
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="authorization_group_grant",
        authorization_group_grant=direct_grant,
        scope="MANAGED_USERS",
        resolver="disabled",
        enabled=True,
    )

    response = client.get(_api_url(app.app_key, "authorization-groups"))

    body = _response_json_object(cast("HttpResponseLike", cast("object", response)))
    group_item = _json_object(_json_list(body["data"])[0])
    grants = [_json_object(grant) for grant in _json_list(group_item["grants"])]
    direct = next(grant for grant in grants if grant["permission"] == direct_permission.key)
    inherited = next(grant for grant in grants if grant["permission"] == inherited_permission.key)
    assert response.status_code == HTTPStatus.OK
    assert _json_object(direct["managed_scope_policy"])["mode"] == "disabled"
    assert direct["effective_managed_scope_policy"] is None
    assert _json_object(inherited["managed_scope_policy"])["mode"] == "inherit"
    assert _json_object(inherited["effective_managed_scope_policy"])["resolver"] == (
        "dingtalk_manager_chain"
    )


def test_authorization_group_payload_uses_prefetched_grants_and_policies() -> None:
    app = App.objects.create(app_key="ops1-catalog-query-count", name="Catalog Query Count")
    scope = AppScope.objects.create(app=app, key="MANAGED_USERS", name="Managed users")
    default_policy = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        scope=scope.key,
        resolver="dingtalk_manager_chain",
    )
    _ = default_policy
    for group_index in range(3):
        group = AuthorizationGroup.objects.create(
            app=app,
            key=f"group-{group_index}",
            kind="role",
            name=f"Group {group_index}",
        )
        for permission_index in range(3):
            permission = Permission.objects.create(
                app=app,
                key=f"permission.{group_index}.{permission_index}",
                name=f"Permission {group_index}.{permission_index}",
                supported_scopes=[scope.key],
            )
            grant = AuthorizationGroupGrant.objects.create(
                authorization_group=group,
                permission=permission,
                scope_key=scope.key,
            )
            if permission_index == 0:
                _ = ManagedScopePolicy.objects.create(
                    app=app,
                    target_type="authorization_group_grant",
                    authorization_group_grant=grant,
                    scope=scope.key,
                    resolver="disabled",
                    enabled=True,
                )

    with CaptureQueriesContext(connection) as queries:
        payload = authorization_groups_payload(app)

    assert len(cast("list[JsonValue]", payload["data"])) == AUTHORIZATION_GROUP_QUERY_COUNT_GROUPS
    assert len(queries) <= AUTHORIZATION_GROUP_PAYLOAD_MAX_QUERIES


def test_authorization_group_api_uses_bounded_pagination_and_query_count() -> None:
    app = App.objects.create(app_key="ops1-catalog-large-authz", name="Large Authz")
    scope = AppScope.objects.create(app=app, key="SELF", name="Self")
    permission = Permission.objects.create(
        app=app,
        key="large.read",
        name="Large Read",
        supported_scopes=[scope.key],
    )
    groups = [
        AuthorizationGroup(
            app=app,
            key=f"group-{index:03d}",
            kind="role",
            name=f"Group {index:03d}",
            is_active=index % 2 == 0,
        )
        for index in range(AUTHORIZATION_GROUP_LARGE_DIRECTORY_SIZE)
    ]
    created_groups = AuthorizationGroup.objects.bulk_create(groups)
    _ = AuthorizationGroupGrant.objects.bulk_create(
        AuthorizationGroupGrant(
            authorization_group=group,
            permission=permission,
            scope_key=scope.key,
        )
        for group in created_groups
    )

    request = _superuser_request(
        "ops1-catalog-large-authz-admin",
        query={
            "include_inactive": "true",
            "page": "2",
            "page_size": str(AUTHORIZATION_GROUP_PAGE_SIZE_UNDER_TEST),
        },
    )

    with CaptureQueriesContext(connection) as queries:
        response = console_authorization_groups(
            request,
            app.app_key,
        )

    body = _response_json_object(cast("HttpResponseLike", cast("object", response)))
    pagination = _json_object(body["pagination"])
    data = _json_list(body["data"])
    assert response.status_code == HTTPStatus.OK
    assert len(data) == AUTHORIZATION_GROUP_PAGE_SIZE_UNDER_TEST
    assert pagination == {
        "page": 2,
        "page_size": AUTHORIZATION_GROUP_PAGE_SIZE_UNDER_TEST,
        "total_items": AUTHORIZATION_GROUP_LARGE_DIRECTORY_SIZE,
        "total_pages": 3,
    }
    assert len(queries) <= AUTHORIZATION_GROUP_PAYLOAD_MAX_QUERIES


def test_authorization_group_api_preserves_status_filter_under_pagination() -> None:
    app = App.objects.create(app_key="ops1-catalog-status-filter", name="Status Filter")
    _ = AuthorizationGroup.objects.create(app=app, key="active", kind="role", name="Active")
    _ = AuthorizationGroup.objects.create(
        app=app,
        key="inactive",
        kind="role",
        name="Inactive",
        is_active=False,
    )

    response = console_authorization_groups(
        _superuser_request(
            "ops1-catalog-status-filter-admin",
            query={"status": "inactive", "include_inactive": "false"},
        ),
        app.app_key,
    )

    body = _response_json_object(cast("HttpResponseLike", cast("object", response)))
    assert response.status_code == HTTPStatus.OK
    assert [_json_object(item)["key"] for item in _json_list(body["data"])] == ["inactive"]
    assert _json_object(body["pagination"])["total_items"] == 1


@pytest.mark.parametrize(
    ("resolver", "expected_mode"),
    [
        ("dingtalk_manager_chain", "override"),
        ("easyauth_team", "easyauth_team"),
        ("union", "union"),
        ("disabled", "disabled"),
    ],
)
def test_ops1_authorization_group_catalog_preserves_grant_resolver(
    resolver: str,
    expected_mode: str,
) -> None:
    client = _logged_in_superuser(f"ops1-catalog-resolver-{resolver}")
    app = App.objects.create(
        app_key=f"ops1-catalog-resolver-{resolver}",
        name=f"Resolver {resolver}",
    )
    scope = AppScope.objects.create(app=app, key="MANAGED_USERS", name="Managed users")
    permission = Permission.objects.create(
        app=app,
        key="order.read",
        name="Read orders",
        supported_scopes=[scope.key],
    )
    group = AuthorizationGroup.objects.create(app=app, key="manager", kind="role", name="Manager")
    grant = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key=scope.key,
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="authorization_group_grant",
        authorization_group_grant=grant,
        scope=scope.key,
        resolver=resolver,
    )

    response = client.get(_api_url(app.app_key, "authorization-groups"))

    body = _response_json_object(response)
    group_item = _json_object(_json_list(body["data"])[0])
    grant_item = _json_object(_json_list(group_item["grants"])[0])
    policy_item = _json_object(grant_item["managed_scope_policy"])
    assert response.status_code == HTTPStatus.OK
    assert policy_item["mode"] == expected_mode
    assert policy_item["resolver"] == resolver


def test_ops1_inactive_member_cannot_read_permission_catalog() -> None:
    client = _logged_in_user("ops1-catalog-inactive")
    app = App.objects.create(app_key="ops1-catalog-inactive", name="Inactive")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-catalog-inactive",
        role="developer",
        is_active=False,
    )

    response = client.get(_api_url(app.app_key, "permissions"))

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "PERMISSION_DENIED" in response.content.decode()
    assert app.app_key not in response.content.decode()


@pytest.mark.parametrize("endpoint", ["roles", "role-permission-matrix"])
def test_legacy_role_catalog_endpoints_are_removed(endpoint: str) -> None:
    client = _logged_in_superuser(f"ops1-legacy-{endpoint}")
    app = App.objects.create(app_key=f"ops1-legacy-{endpoint}", name="Legacy removed")

    response = client.get(_api_url(app.app_key, endpoint))

    assert response.status_code == HTTPStatus.NOT_FOUND


def _member_app(app_key: str, username: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role=role)
    return app


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


def _response_json_object(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed


def _json_object(value: JsonValue) -> dict[str, JsonValue]:
    assert isinstance(value, dict), value
    return value


def _json_list(value: JsonValue) -> list[JsonValue]:
    assert isinstance(value, list), value
    return value


def _logged_in_user(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_user(client, username)


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    _ = authenticate_console_admin(client, username)
    return client


def _superuser_request(username: str, *, query: dict[str, str]) -> HttpRequest:
    client = _logged_in_superuser(username)
    request = RequestFactory().get("/console/api/v1/apps/example/authorization-groups", data=query)
    request.session = client.session
    return request

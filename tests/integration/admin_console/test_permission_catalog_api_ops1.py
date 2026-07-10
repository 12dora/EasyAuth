from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Final, Protocol

import pytest
from django.test import Client
from pydantic import TypeAdapter

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
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

if TYPE_CHECKING:
    from django.conf import LazySettings

pytestmark = pytest.mark.django_db

JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@pytest.fixture(autouse=True)
def _console_superuser_groups(settings: LazySettings) -> None:  # pyright: ignore[reportUnusedFunction]
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)


class HttpResponseLike(Protocol):
    content: bytes


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
        target_id=app.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="authorization_group_grant",
        target_id=direct_grant.id,
        scope="MANAGED_USERS",
        resolver="disabled",
        enabled=True,
    )

    response = client.get(_api_url(app.app_key, "authorization-groups"))

    body = _response_json_object(response)
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
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client


def _logged_in_superuser(username: str) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session["easyauth_authentik_groups"] = ["easyauth-admins"]
    session.save()
    return client

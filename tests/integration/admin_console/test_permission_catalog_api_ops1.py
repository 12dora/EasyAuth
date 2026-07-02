from __future__ import annotations

from http import HTTPStatus
from json import dumps
from re import escape, search
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
    Role,
    RolePermission,
)
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from django.conf import LazySettings

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-catalog"
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@pytest.fixture(autouse=True)
def _console_superuser_groups(settings: LazySettings) -> None:  # pyright: ignore[reportUnusedFunction]
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)


class HttpResponseLike(Protocol):
    content: bytes


def test_ops1_owner_reads_permission_tree_catalog_for_owned_app() -> None:
    # Given: owner 管理一个存在分组、子分组和权限的 App。
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

    # When: owner 读取权限树。
    response = client.get(_api_url(app.app_key, "permission-tree"))

    # Then: API 返回该 App 的 active 权限树, 不暴露 inactive 权限。
    body = response.content.decode()
    tree = _response_json_object(response)
    root_node = _json_object(_json_list(tree["groups"])[0])
    child_node = _json_object(_json_list(root_node["children"])[0])
    permission_node = _json_object(_json_list(child_node["children"])[0])
    assert response.status_code == HTTPStatus.OK
    assert _json_string(body, "app_key") == app.app_key
    assert "PIPELINE" in body
    assert "PIPELINE_BUILD" in body
    assert "pipeline.run" in body
    assert "inactive.permission" not in body
    assert _json_object(_json_list(child_node["permissions"])[0])["key"] == "pipeline.run"
    assert permission_node["type"] == "permission"
    assert permission_node["key"] == "pipeline.run"


def test_ops1_developer_reads_role_permission_matrix_for_member_app() -> None:
    # Given: developer 是 App active 成员, App 已有角色权限矩阵。
    client = _logged_in_user("ops1-catalog-developer")
    app = _member_app("ops1-catalog-matrix", "ops1-catalog-developer", role="developer")
    role = Role.objects.create(app=app, key="operator", name="Operator")
    permission = Permission.objects.create(app=app, key="pipeline.read", name="Read pipeline")
    _ = RolePermission.objects.create(role=role, permission=permission)

    # When: developer 读取矩阵。
    response = client.get(_api_url(app.app_key, "role-permission-matrix"))

    # Then: API 返回角色、权限、已勾选关系和版本号。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert _json_string(body, "version") != ""
    assert "operator" in body
    assert "pipeline.read" in body
    assert '"enabled": true' in body


def test_ops1_superuser_reads_authorization_group_grant_managed_scope_policy() -> None:
    # Given: superuser 管理一个含 App 默认策略、grant 覆盖策略和继承 grant 的 App。
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

    # When: owner 读取授权组目录。
    response = client.get(_api_url(app.app_key, "authorization-groups"))

    # Then: 每个 grant 返回自身策略、有效策略、继承来源和健康状态。
    body = _response_json_object(response)
    group_item = _json_object(_json_list(body["items"])[0])
    grants = [_json_object(grant) for grant in _json_list(group_item["grants"])]
    direct = next(grant for grant in grants if grant["permission"] == direct_permission.key)
    inherited = next(grant for grant in grants if grant["permission"] == inherited_permission.key)
    assert response.status_code == HTTPStatus.OK
    assert direct["managed_scope_policy"] == {
        "mode": "disabled",
        "resolver": "disabled",
        "enabled": True,
        "source": "authorization_group_grant",
        "health_status": "disabled",
        "health_message": "当前 grant 不启用管理范围授权。",
    }
    assert direct["effective_managed_scope_policy"] is None
    assert inherited["managed_scope_policy"] == {
        "mode": "inherit",
        "resolver": "",
        "enabled": False,
        "source": "app_default",
        "health_status": "healthy",
        "health_message": "继承应用默认管理范围策略。",
    }
    assert inherited["effective_managed_scope_policy"] == {
        "resolver": "dingtalk_manager_chain",
        "enabled": True,
        "source": "app_default",
        "inherited_from": "app_default",
        "health_status": "healthy",
        "health_message": "管理范围策略已配置。",
    }


def test_ops1_inactive_member_cannot_read_permission_catalog() -> None:
    # Given: 用户只有 inactive AppMembership。
    client = _logged_in_user("ops1-catalog-inactive")
    app = App.objects.create(app_key="ops1-catalog-inactive", name="Inactive")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-catalog-inactive",
        role="developer",
        is_active=False,
    )

    # When: 用户读取该 App 权限列表。
    response = client.get(_api_url(app.app_key, "permissions"))

    # Then: API 拒绝非 active owner/developer。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert "PERMISSION_DENIED" in body
    assert app.app_key not in body


def test_ops1_superuser_reads_roles_without_membership() -> None:
    # Given: App 没有成员关系, 但系统管理员已登录。
    client = _logged_in_superuser("ops1-catalog-admin")
    app = App.objects.create(app_key="ops1-catalog-admin", name="Admin")
    _ = Role.objects.create(app=app, key="admin", name="Admin")

    # When: superuser 读取角色列表。
    response = client.get(_api_url(app.app_key, "roles"))

    # Then: API 允许系统管理员读取。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert "admin" in body


def test_ops1_matrix_post_saves_assignment_and_rejects_stale_version() -> None:
    # Given: owner 打开当前矩阵版本。
    client = _logged_in_user("ops1-catalog-save")
    app = _member_app("ops1-catalog-save", "ops1-catalog-save", role="owner")
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    initial = client.get(_api_url(app.app_key, "role-permission-matrix"))
    initial_body = initial.content.decode()
    initial_version = _json_string(initial_body, "version")

    # When: owner 使用当前版本保存矩阵, 随后用旧版本再次提交。
    accepted = client.post(
        _api_url(app.app_key, "role-permission-matrix"),
        data=_matrix_payload(
            version=initial_version,
            role_id=role.id,
            permission_id=permission.id,
            enabled=True,
        ),
        content_type="application/json",
    )
    stale = client.post(
        _api_url(app.app_key, "role-permission-matrix"),
        data=_matrix_payload(
            version=initial_version,
            role_id=role.id,
            permission_id=permission.id,
            enabled=False,
        ),
        content_type="application/json",
    )

    # Then: 首次写入 RolePermission 和审计, 旧版本提交返回 409。
    assert accepted.status_code == HTTPStatus.OK
    assert RolePermission.objects.filter(role=role, permission=permission).exists() is True
    assert AuditLog.objects.filter(event_type="role_permission_matrix_updated").exists() is True
    assert AuditLog.objects.filter(event_type="role_permission_matrix_changed").exists() is True
    assert stale.status_code == HTTPStatus.CONFLICT
    assert "CONFLICT" in stale.content.decode()


def test_ops1_developer_cannot_create_role_permission_with_matrix_post() -> None:
    # Given: developer 可读取 App 矩阵, 但不是 owner。
    client = _logged_in_user("ops1-catalog-dev-write-post")
    app = _member_app(
        "ops1-catalog-dev-write-post",
        "ops1-catalog-dev-write-post",
        role="developer",
    )
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    initial = client.get(_api_url(app.app_key, "role-permission-matrix"))
    initial_version = _json_string(initial.content.decode(), "version")

    # When: developer 尝试通过矩阵 API 写入 RolePermission。
    response = client.post(
        _api_url(app.app_key, "role-permission-matrix"),
        data=_matrix_payload(
            version=initial_version,
            role_id=role.id,
            permission_id=permission.id,
            enabled=True,
        ),
        content_type="application/json",
    )

    # Then: API 拒绝非 owner 写操作, 且不创建 RolePermission 或配置审计。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert RolePermission.objects.filter(role=role, permission=permission).exists() is False
    assert AuditLog.objects.count() == 0


def test_ops1_developer_cannot_delete_role_permission_with_matrix_patch() -> None:
    # Given: developer 可读取 App 矩阵, 但不是 owner。
    client = _logged_in_user("ops1-catalog-dev-write-patch")
    app = _member_app(
        "ops1-catalog-dev-write-patch",
        "ops1-catalog-dev-write-patch",
        role="developer",
    )
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    _ = RolePermission.objects.create(role=role, permission=permission)
    initial = client.get(_api_url(app.app_key, "role-permission-matrix"))
    initial_version = _json_string(initial.content.decode(), "version")

    # When: developer 尝试通过矩阵 API 删除 RolePermission。
    response = client.patch(
        _api_url(app.app_key, "role-permission-matrix"),
        data=_matrix_payload(
            version=initial_version,
            role_id=role.id,
            permission_id=permission.id,
            enabled=False,
        ),
        content_type="application/json",
    )

    # Then: API 拒绝非 owner 写操作, 且不删除 RolePermission 或写入配置审计。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert RolePermission.objects.filter(role=role, permission=permission).exists() is True
    assert AuditLog.objects.count() == 0


def test_ops1_matrix_batch_save_rejects_invalid_assignment_without_partial_writes() -> None:
    # Given: owner 准备批量保存矩阵, 其中一个 assignment 指向其他 App 的 Permission。
    client = _logged_in_user("ops1-catalog-batch-invalid")
    app = _member_app("ops1-catalog-batch-invalid", "ops1-catalog-batch-invalid", role="owner")
    role = Role.objects.create(app=app, key="auditor", name="Auditor")
    permission = Permission.objects.create(app=app, key="invoice.read", name="Read invoices")
    other_app = App.objects.create(app_key="ops1-catalog-batch-other", name="Other")
    other_permission = Permission.objects.create(
        app=other_app,
        key="other.read",
        name="Other read",
    )
    initial = client.get(_api_url(app.app_key, "role-permission-matrix"))
    initial_version = _json_string(initial.content.decode(), "version")

    # When: owner 提交一个合法 assignment 和一个非法 assignment。
    response = client.post(
        _api_url(app.app_key, "role-permission-matrix"),
        data=dumps(
            {
                "version": initial_version,
                "assignments": [
                    {"role_id": role.id, "permission_id": permission.id, "enabled": True},
                    {"role_id": role.id, "permission_id": other_permission.id, "enabled": True},
                ],
            },
        ),
        content_type="application/json",
    )

    # Then: API 返回 400, 合法 assignment 也不会部分写入 RolePermission 或审计。
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert RolePermission.objects.count() == 0
    assert AuditLog.objects.count() == 0


def _member_app(app_key: str, username: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role=role)
    return app


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


def _matrix_payload(*, version: str, role_id: int, permission_id: int, enabled: bool) -> str:
    enabled_value = "true" if enabled else "false"
    return (
        '{"version":"'
        f"{version}"
        '","assignments":[{"role_id":'
        f"{role_id}"
        ',"permission_id":'
        f"{permission_id}"
        ',"enabled":'
        f"{enabled_value}"
        "}]}"
    )


def _json_string(body: str, key: str) -> str:
    match = search(rf'"{escape(key)}"\s*:\s*"([^"]*)"', body)
    if match is None:
        raise AssertionError(body)
    return match.group(1)


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
    return _authentik_client(username)


def _logged_in_superuser(username: str) -> Client:
    return _authentik_client(username, groups=("easyauth-admins",))


def _authentik_client(username: str, *, groups: tuple[str, ...] = ()) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session["easyauth_authentik_groups"] = list(groups or ("EasyAuth Admins",))
    session.save()
    return client

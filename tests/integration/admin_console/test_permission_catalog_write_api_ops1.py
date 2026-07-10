from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from easyauth.api.errors import ErrorCode
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
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-catalog-write"
UPDATED_GROUP_ORDER: Final = 20
MOVED_SOURCE_DEPTH: Final = 3
MOVED_CHILD_DEPTH: Final = 4
MOVED_GRANDCHILD_DEPTH: Final = 5


def test_ops1_owner_creates_and_updates_permission_group() -> None:
    # Given: owner 管理一个 App。
    client = _logged_in_user("ops1-catalog-group-owner")
    app = _member_app("ops1-catalog-group-write", "ops1-catalog-group-owner", role="owner")

    # When: owner 创建权限分组后更新名称和排序。
    created = client.post(
        _api_url(app.app_key, "permission-groups"),
        data=dumps({"key": "PIPELINE", "name": "Pipeline", "display_order": 10}),
        content_type="application/json",
    )
    assert created.status_code == HTTPStatus.CREATED
    group = PermissionGroup.objects.get(app=app, key="PIPELINE")
    updated = client.patch(
        _api_url(app.app_key, "permission-groups"),
        data=dumps({"id": group.id, "name": "Pipeline Ops", "display_order": UPDATED_GROUP_ORDER}),
        content_type="application/json",
    )

    # Then: API 返回创建和更新后的权限分组。
    group.refresh_from_db()
    assert updated.status_code == HTTPStatus.OK
    assert group.name == "Pipeline Ops"
    assert group.display_order == UPDATED_GROUP_ORDER
    assert "Pipeline Ops" in updated.content.decode()


def test_ops1_owner_creates_and_updates_permission_with_group() -> None:
    # Given: owner 管理一个包含权限分组的 App。
    client = _logged_in_user("ops1-catalog-permission-owner")
    app = _member_app(
        "ops1-catalog-permission-write",
        "ops1-catalog-permission-owner",
        role="owner",
    )
    group = PermissionGroup.objects.create(app=app, key="BILLING", name="Billing")
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")

    # When: owner 在分组下创建权限后更新名称。
    created = client.post(
        _api_url(app.app_key, "permissions"),
        data=dumps(
            {
                "key": "billing.read",
                "name": "Read billing",
                "group_key": group.key,
                "supported_scopes": [scope.key],
            },
        ),
        content_type="application/json",
    )
    assert created.status_code == HTTPStatus.CREATED
    permission = Permission.objects.get(app=app, key="billing.read")
    updated = client.patch(
        _api_url(app.app_key, "permissions"),
        data=dumps({"id": permission.id, "name": "Read billing records"}),
        content_type="application/json",
    )

    # Then: API 返回创建和更新后的权限。
    permission.refresh_from_db()
    assert updated.status_code == HTTPStatus.OK
    assert permission.group == group
    assert permission.name == "Read billing records"
    assert f'"group_key": "{group.key}"' in updated.content.decode()


def test_ops1_owner_writes_authorization_group_grant_managed_scope_policy() -> None:
    # Given: owner 管理一个带 MANAGED_USERS Scope 的 App。
    client = _logged_in_user("ops1-catalog-authz-policy")
    app = _member_app("ops1-catalog-authz-policy", "ops1-catalog-authz-policy", role="owner")
    scope = AppScope.objects.create(app=app, key="MANAGED_USERS", name="Managed users")
    permission = Permission.objects.create(
        app=app,
        key="order.read",
        name="Read orders",
        supported_scopes=[scope.key],
    )

    # When: owner 创建授权组 grant 覆盖策略, 随后改为 disabled, 最后移除 grant。
    created = client.post(
        _api_url(app.app_key, "authorization-groups"),
        data=dumps(
            {
                "key": "manager",
                "kind": "role",
                "name": "Manager",
                "grants": [
                    {
                        "permission": permission.key,
                        "scope": scope.key,
                        "managed_scope_policy": {
                            "mode": "override",
                            "resolver": "dingtalk_manager_chain",
                            "enabled": True,
                        },
                    },
                ],
            },
        ),
        content_type="application/json",
    )
    assert created.status_code == HTTPStatus.CREATED
    grant = AuthorizationGroupGrant.objects.get(
        authorization_group__app=app,
        authorization_group__key="manager",
        permission=permission,
        scope_key=scope.key,
    )
    policy = ManagedScopePolicy.objects.get(
        app=app,
        target_type="authorization_group_grant",
        target_id=grant.id,
        scope="MANAGED_USERS",
    )
    assert policy.resolver == "dingtalk_manager_chain"
    assert policy.enabled is True

    disabled = client.patch(
        _authorization_group_detail_url(app.app_key, "manager"),
        data=dumps(
            {
                "key": "manager",
                "kind": "role",
                "name": "Manager",
                "grants": [
                    {
                        "permission": permission.key,
                        "scope": scope.key,
                        "managed_scope_policy": {
                            "mode": "disabled",
                            "resolver": "disabled",
                            "enabled": True,
                        },
                    },
                ],
            },
        ),
        content_type="application/json",
    )
    policy.refresh_from_db()
    assert disabled.status_code == HTTPStatus.OK
    assert policy.resolver == "disabled"
    assert policy.enabled is True

    inherited = client.patch(
        _authorization_group_detail_url(app.app_key, "manager"),
        data=dumps(
            {
                "key": "manager",
                "kind": "role",
                "name": "Manager",
                "grants": [
                    {
                        "permission": permission.key,
                        "scope": scope.key,
                        "managed_scope_policy": {"mode": "inherit"},
                    },
                ],
            },
        ),
        content_type="application/json",
    )
    grant.refresh_from_db()
    assert inherited.status_code == HTTPStatus.OK
    assert grant.is_active is True
    assert ManagedScopePolicy.objects.filter(
        app=app,
        target_type="authorization_group_grant",
        target_id=grant.id,
        scope="MANAGED_USERS",
    ).exists() is False
    policy_audits = list(
        AuditLog.objects.filter(event_type="managed_scope_policy_updated").order_by("id"),
    )
    assert [audit.target_type for audit in policy_audits] == [
        "authorization_group_grant",
        "authorization_group_grant",
        "authorization_group_grant",
    ]
    assert [audit.metadata for audit in policy_audits] == [
        {
            "app_key": app.app_key,
            "authorization_group_key": "manager",
            "permission_key": permission.key,
            "scope": "MANAGED_USERS",
            "resolver": "dingtalk_manager_chain",
        },
        {
            "app_key": app.app_key,
            "authorization_group_key": "manager",
            "permission_key": permission.key,
            "scope": "MANAGED_USERS",
            "resolver": "disabled",
        },
        {
            "app_key": app.app_key,
            "authorization_group_key": "manager",
            "permission_key": permission.key,
            "scope": "MANAGED_USERS",
            "resolver": "app_default",
        },
    ]

    removed = client.patch(
        _authorization_group_detail_url(app.app_key, "manager"),
        data=dumps(
            {
                "key": "manager",
                "kind": "role",
                "name": "Manager",
                "grants": [],
            },
        ),
        content_type="application/json",
    )

    grant.refresh_from_db()
    assert removed.status_code == HTTPStatus.OK
    assert grant.is_active is False
    assert ManagedScopePolicy.objects.filter(
        app=app,
        target_type="authorization_group_grant",
        target_id=grant.id,
        scope="MANAGED_USERS",
    ).exists() is False


def test_ops1_catalog_writes_persist_bilingual_display_fields() -> None:
    # Given: owner 管理一个 App。
    client = _logged_in_user("ops1-catalog-bilingual-owner")
    app = _member_app("ops1-catalog-bilingual", "ops1-catalog-bilingual-owner", role="owner")

    # When: owner 创建 scope/permission group/permission/authorization group 时携带双语字段。
    scope_created = client.post(
        _api_url(app.app_key, "scopes"),
        data=dumps(
            {
                "key": "GLOBAL",
                "name": "全局",
                "name_en": "Global",
                "description_en": "All users",
            },
        ),
        content_type="application/json",
    )
    group_created = client.post(
        _api_url(app.app_key, "permission-groups"),
        data=dumps({"key": "billing", "name": "账务", "name_en": "Billing"}),
        content_type="application/json",
    )
    assert group_created.status_code == HTTPStatus.CREATED
    group = PermissionGroup.objects.get(app=app, key="billing")
    permission_created = client.post(
        _api_url(app.app_key, "permissions"),
        data=dumps(
            {
                "key": "billing.read",
                "name": "查看账务",
                "name_en": "Read billing",
                "group_key": group.key,
                "supported_scopes": ["GLOBAL"],
            },
        ),
        content_type="application/json",
    )
    authz_created = client.post(
        _api_url(app.app_key, "authorization-groups"),
        data=dumps(
            {
                "key": "accountant",
                "kind": "role",
                "name": "会计",
                "name_en": "Accountant",
                "description_en": "Accountant role",
                "grants": [{"permission": "billing.read", "scope": "GLOBAL"}],
            },
        ),
        content_type="application/json",
    )

    # Then: 双语字段落库并出现在响应 payload 中。
    scope = AppScope.objects.get(app=app, key="GLOBAL")
    permission = Permission.objects.get(app=app, key="billing.read")
    authz_group = AuthorizationGroup.objects.get(app=app, key="accountant")
    assert scope_created.status_code == HTTPStatus.CREATED
    assert permission_created.status_code == HTTPStatus.CREATED
    assert authz_created.status_code == HTTPStatus.CREATED
    assert (scope.name_en, scope.description_en) == ("Global", "All users")
    assert group.name_en == "Billing"
    assert permission.name_en == "Read billing"
    assert (authz_group.name_en, authz_group.description_en) == ("Accountant", "Accountant role")
    assert '"name_en": "Global"' in scope_created.content.decode()
    assert '"name_en": "Accountant"' in authz_created.content.decode()

    # When: owner 通过 PATCH 更新双语字段(含 key route)。
    scope_updated = client.patch(
        f"{_api_url(app.app_key, 'scopes')}/GLOBAL",
        data=dumps({"description_en": "All tenant users"}),
        content_type="application/json",
    )
    permission_updated = client.patch(
        _api_url(app.app_key, "permissions"),
        data=dumps(
            {
                "id": permission.id,
                "name_en": "Read billing records",
                "description_en": "Read-only billing access",
            },
        ),
        content_type="application/json",
    )

    # Then: PATCH 只覆盖显式提交的双语字段。
    scope.refresh_from_db()
    permission.refresh_from_db()
    assert scope_updated.status_code == HTTPStatus.OK
    assert permission_updated.status_code == HTTPStatus.OK
    assert (scope.name_en, scope.description_en) == ("Global", "All tenant users")
    assert (permission.name_en, permission.description_en) == (
        "Read billing records",
        "Read-only billing access",
    )
    assert '"name_en": "Read billing records"' in permission_updated.content.decode()

    # Then: 目录读取接口返回双语字段。
    listed = client.get(_api_url(app.app_key, "scopes"))
    assert listed.status_code == HTTPStatus.OK
    assert '"name_en": "Global"' in listed.content.decode()
    assert '"description_en": "All tenant users"' in listed.content.decode()


def test_ops1_permission_patch_rejects_deprecated_permission_reactivation() -> None:
    # Given: 模板导入已废弃一个 Permission。
    client = _logged_in_user("ops1-catalog-permission-deprecated")
    app = _member_app(
        "ops1-catalog-permission-deprecated",
        "ops1-catalog-permission-deprecated",
        role="owner",
    )
    permission = Permission.objects.create(
        app=app,
        key="legacy.read",
        name="Legacy read",
        is_active=False,
        deprecated_at=timezone.now(),
        deprecated_reason="permission template missing",
    )

    # When: owner 试图仅通过 is_active 重新启用该 Permission。
    response = client.patch(
        _api_url(app.app_key, "permissions"),
        data=dumps({"id": permission.id, "is_active": True}),
        content_type="application/json",
    )

    # Then: API 拒绝重新启用, 防止控制台和运行时权限查询状态不一致。
    permission.refresh_from_db()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert ErrorCode.SEMANTIC_VALIDATION_ERROR in response.content.decode()
    assert permission.is_active is False
    assert permission.deprecated_at is not None
    assert permission.deprecated_reason == "permission template missing"


def test_ops1_permission_group_move_updates_descendant_depths() -> None:
    # Given: owner 管理一个三层权限分组树。
    client = _logged_in_user("ops1-catalog-group-move")
    app = _member_app("ops1-catalog-group-move", "ops1-catalog-group-move", role="owner")
    source = PermissionGroup.objects.create(app=app, key="SOURCE", name="Source")
    child = PermissionGroup.objects.create(
        app=app,
        key="SOURCE_CHILD",
        name="Source child",
        parent=source,
        depth=2,
    )
    grandchild = PermissionGroup.objects.create(
        app=app,
        key="SOURCE_GRANDCHILD",
        name="Source grandchild",
        parent=child,
        depth=3,
    )
    target_root = PermissionGroup.objects.create(app=app, key="TARGET", name="Target")
    target_parent = PermissionGroup.objects.create(
        app=app,
        key="TARGET_PARENT",
        name="Target parent",
        parent=target_root,
        depth=2,
    )

    # When: owner 把包含子节点的分组移动到新的二级父节点下。
    response = client.patch(
        _api_url(app.app_key, "permission-groups"),
        data=dumps({"id": source.id, "parent_key": target_parent.key}),
        content_type="application/json",
    )

    # Then: 被移动分组及其所有后代 depth 都随新位置更新。
    source.refresh_from_db()
    child.refresh_from_db()
    grandchild.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert source.depth == MOVED_SOURCE_DEPTH
    assert child.depth == MOVED_CHILD_DEPTH
    assert grandchild.depth == MOVED_GRANDCHILD_DEPTH


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("permission-groups", {"key": "PIPELINE", "name": "Pipeline"}),
        ("permissions", {"key": "invoice.read", "name": "Read invoices"}),
    ],
)
def test_ops1_developer_cannot_write_catalog_resources(
    endpoint: str,
    payload: dict[str, str],
) -> None:
    # Given: developer 可读取 App 权限目录, 但不是 owner。
    client = _logged_in_user(f"ops1-catalog-{endpoint}-developer")
    app = _member_app(
        f"ops1-catalog-{endpoint}-developer",
        f"ops1-catalog-{endpoint}-developer",
        role="developer",
    )

    # When: developer 尝试创建 catalog 资源。
    response = client.post(
        _api_url(app.app_key, endpoint),
        data=dumps(payload),
        content_type="application/json",
    )

    # Then: API 拒绝非 owner 写操作。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert ErrorCode.PERMISSION_DENIED in response.content.decode()


@pytest.mark.parametrize(
    ("endpoint", "payload"),
    [
        ("permission-groups", {"key": "PIPELINE", "name": "Duplicate"}),
        ("permissions", {"key": "invoice.read", "name": "Duplicate"}),
    ],
)
def test_ops1_catalog_create_rejects_duplicate_key_for_same_app(
    endpoint: str,
    payload: dict[str, str],
) -> None:
    # Given: owner 管理的 App 已存在同 key catalog 资源。
    client = _logged_in_user(f"ops1-catalog-{endpoint}-duplicate")
    app = _member_app(
        f"ops1-catalog-{endpoint}-duplicate",
        f"ops1-catalog-{endpoint}-duplicate",
        role="owner",
    )
    _seed_resource(app=app, endpoint=endpoint, key=payload["key"])

    # When: owner 使用同 key 再次创建资源。
    response = client.post(
        _api_url(app.app_key, endpoint),
        data=dumps(payload),
        content_type="application/json",
    )

    # Then: API 返回 key 冲突。
    assert response.status_code == HTTPStatus.CONFLICT
    assert ErrorCode.CONFLICT in response.content.decode()


def test_ops1_catalog_write_rejects_cross_app_relationships() -> None:
    # Given: owner 管理当前 App, 请求体引用其他 App 的 group。
    client = _logged_in_user("ops1-catalog-cross-app-owner")
    app = _member_app("ops1-catalog-cross-app", "ops1-catalog-cross-app-owner", role="owner")
    other_app = App.objects.create(app_key="ops1-catalog-cross-app-other", name="Other")
    other_group = PermissionGroup.objects.create(app=other_app, key="OTHER", name="Other")

    # When: owner 创建 Permission 时绑定其他 App 的 PermissionGroup。
    response = client.post(
        _api_url(app.app_key, "permissions"),
        data=dumps({"key": "other.read", "name": "Other read", "group_key": other_group.key}),
        content_type="application/json",
    )

    # Then: API 返回语义校验错误。
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert ErrorCode.SEMANTIC_VALIDATION_ERROR in response.content.decode()


def _member_app(app_key: str, username: str, *, role: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role=role)
    return app


def _api_url(app_key: str, endpoint: str) -> str:
    return f"/console/api/v1/apps/{app_key}/{endpoint}"


def _authorization_group_detail_url(app_key: str, authorization_group_key: str) -> str:
    return f"{_api_url(app_key, 'authorization-groups')}/{authorization_group_key}"


def _seed_resource(*, app: App, endpoint: str, key: str) -> None:
    match endpoint:
        case "permission-groups":
            _ = PermissionGroup.objects.create(app=app, key=key, name=key)
        case "permissions":
            _ = Permission.objects.create(app=app, key=key, name=key)
        case unreachable:
            raise AssertionError(unreachable)


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client

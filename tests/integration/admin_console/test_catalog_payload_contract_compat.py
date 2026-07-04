from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import Final, Protocol

import pytest
from django.contrib.auth.models import User
from django.test import Client
from pydantic import TypeAdapter

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import App, AppMembership, AppScope, Permission, PermissionGroup

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-catalog-payload-contract"
APPS_API_URL: Final = "/console/api/v1/apps"
ROOT_GROUP_DEPTH: Final = 1
CHILD_GROUP_DEPTH: Final = 2
JSON_VALUE_ADAPTER: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


class HttpResponseLike(Protocol):
    content: bytes


def test_permission_group_writes_accept_parent_key_contract() -> None:
    # Given: owner 管理一个包含两个父分组的 App。
    client = _logged_in_user("catalog-payload-group-owner")
    app = _member_app("catalog-payload-group", "catalog-payload-group-owner")
    parent = PermissionGroup.objects.create(app=app, key="ROOT", name="Root")
    target = PermissionGroup.objects.create(app=app, key="TARGET", name="Target")

    # When: owner 使用 parent_key 创建子分组, 再通过 key route 移动到另一个父分组。
    created = client.post(
        f"{APPS_API_URL}/{app.app_key}/permission-groups",
        data=dumps({"key": "CHILD", "name": "Child", "parent_key": parent.key}),
        content_type="application/json",
    )
    moved = client.patch(
        f"{APPS_API_URL}/{app.app_key}/permission-groups/CHILD",
        data=dumps({"parent_key": target.key}),
        content_type="application/json",
    )

    # Then: API 按 key 解析父分组并返回兼容 parent_key 字段。
    child = PermissionGroup.objects.get(app=app, key="CHILD")
    assert created.status_code == HTTPStatus.CREATED
    assert moved.status_code == HTTPStatus.OK
    assert child.parent == target
    assert child.depth == target.depth + 1
    assert _response_item(moved)["parent_key"] == target.key


def test_permission_writes_accept_group_key_contract() -> None:
    # Given: owner 管理一个包含两个权限分组的 App。
    client = _logged_in_user("catalog-payload-permission-owner")
    app = _member_app("catalog-payload-permission", "catalog-payload-permission-owner")
    source = PermissionGroup.objects.create(app=app, key="SOURCE", name="Source")
    target = PermissionGroup.objects.create(app=app, key="TARGET", name="Target")
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="Global")

    # When: owner 使用 group_key 创建 Permission, 再通过 key route 移动到另一个分组。
    created = client.post(
        f"{APPS_API_URL}/{app.app_key}/permissions",
        data=dumps(
            {
                "key": "report.read",
                "name": "Read report",
                "group_key": source.key,
                "supported_scopes": [scope.key],
            },
        ),
        content_type="application/json",
    )
    moved = client.patch(
        f"{APPS_API_URL}/{app.app_key}/permissions/report.read",
        data=dumps({"group_key": target.key}),
        content_type="application/json",
    )

    # Then: API 按 key 解析权限分组并保留响应中的 group_key。
    permission = Permission.objects.get(app=app, key="report.read")
    assert created.status_code == HTTPStatus.CREATED
    assert moved.status_code == HTTPStatus.OK
    assert permission.group == target
    assert _response_item(moved)["group_key"] == target.key


def test_permission_patch_accepts_deprecated_reason_contract() -> None:
    # Given: owner 管理一个仍 active 的旧 Permission。
    client = _logged_in_user("catalog-payload-deprecate-owner")
    app = _member_app("catalog-payload-deprecate", "catalog-payload-deprecate-owner")
    permission = Permission.objects.create(app=app, key="legacy.read", name="Legacy read")

    # When: owner 通过 key route 写入 deprecated_reason, 即使同请求误传 is_active=true。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}/permissions/{permission.key}",
        data=dumps({"is_active": True, "deprecated_reason": "改用 report.read"}),
        content_type="application/json",
    )

    # Then: Permission 被标记为废弃, 且响应暴露可观察的废弃信息。
    permission.refresh_from_db()
    item = _response_item(response)
    assert response.status_code == HTTPStatus.OK
    assert permission.is_active is False
    assert permission.deprecated_reason == "改用 report.read"
    assert permission.deprecated_at is not None
    assert item["is_deprecated"] is True
    assert item["deprecated_reason"] == "改用 report.read"
    assert isinstance(item["deprecated_at"], str)

    # When: owner 试图直接重新启用已废弃 Permission。
    reactivated = client.patch(
        f"{APPS_API_URL}/{app.app_key}/permissions/{permission.key}",
        data=dumps({"is_active": True}),
        content_type="application/json",
    )

    # Then: API 保持已废弃权限不能重新启用的既有行为。
    permission.refresh_from_db()
    assert reactivated.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert ErrorCode.SEMANTIC_VALIDATION_ERROR in reactivated.content.decode()
    assert permission.is_active is False
    assert permission.deprecated_at is not None


def test_permission_patch_deprecated_reason_keeps_permission_inactive_when_is_active_true() -> None:
    # Given: owner 管理一个仍 active 的旧 Permission。
    client = _logged_in_user("catalog-payload-deprecate-active-owner")
    app = _member_app("catalog-payload-deprecate-active", "catalog-payload-deprecate-active-owner")
    permission = Permission.objects.create(app=app, key="legacy.export", name="Legacy export")

    # When: owner 在同一个 PATCH 中提交 deprecated_reason 和 is_active=true。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}/permissions/{permission.key}",
        data=dumps({"is_active": True, "deprecated_reason": "改用 report.export"}),
        content_type="application/json",
    )

    # Then: API 不允许产生 deprecated_at 非空但仍 active 的安全矛盾状态。
    permission.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert permission.is_active is False
    assert permission.deprecated_at is not None
    assert permission.deprecated_reason == "改用 report.export"


def test_permission_group_move_rolls_back_when_descendant_depth_fails() -> None:
    # Given: owner 管理一个带子节点的分组, 目标父节点会让子节点超过最大 depth。
    client = _logged_in_user("catalog-payload-rollback-owner")
    app = _member_app("catalog-payload-rollback", "catalog-payload-rollback-owner")
    source = PermissionGroup.objects.create(app=app, key="SOURCE", name="Source")
    child = PermissionGroup.objects.create(
        app=app,
        key="SOURCE_CHILD",
        name="Source child",
        parent=source,
        depth=2,
    )
    target_root = PermissionGroup.objects.create(app=app, key="TARGET_ROOT", name="Target root")
    target_level_2 = PermissionGroup.objects.create(
        app=app,
        key="TARGET_LEVEL_2",
        name="Target level 2",
        parent=target_root,
        depth=2,
    )
    target_level_3 = PermissionGroup.objects.create(
        app=app,
        key="TARGET_LEVEL_3",
        name="Target level 3",
        parent=target_level_2,
        depth=3,
    )
    target_level_4 = PermissionGroup.objects.create(
        app=app,
        key="TARGET_LEVEL_4",
        name="Target level 4",
        parent=target_level_3,
        depth=4,
    )

    # When: owner 尝试把 source 移到 depth=4 的目标父节点下。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}/permission-groups",
        data=dumps({"id": source.id, "parent_key": target_level_4.key}),
        content_type="application/json",
    )

    # Then: API 返回语义错误, 且已移动节点和后代都回滚到原位置。
    source.refresh_from_db()
    child.refresh_from_db()
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert ErrorCode.SEMANTIC_VALIDATION_ERROR in response.content.decode()
    assert source.parent is None
    assert source.depth == ROOT_GROUP_DEPTH
    assert child.parent == source
    assert child.depth == CHILD_GROUP_DEPTH


def _member_app(app_key: str, username: str) -> App:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppMembership.objects.create(app=app, user_id=username, role="owner")
    return app


def _logged_in_user(username: str) -> Client:
    _ = User.objects.create_user(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    assert client.login(username=username, password=LOGIN_VALUE) is True
    return client


def _response_item(response: HttpResponseLike) -> dict[str, JsonValue]:
    body = _response_json_object(response)
    item = body["item"]
    assert isinstance(item, dict), item
    return item


def _response_json_object(response: HttpResponseLike) -> dict[str, JsonValue]:
    parsed = JSON_VALUE_ADAPTER.validate_json(response.content)
    assert isinstance(parsed, dict), response.content.decode()
    return parsed

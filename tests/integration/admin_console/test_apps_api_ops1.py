from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_GROUPS_SESSION_KEY, AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.applications.models import (
    App,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
    PermissionGroup,
)
from easyauth.applications.services import StaticTokenService
from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from django.conf import LazySettings

pytestmark = pytest.mark.django_db

LOGIN_VALUE: Final = "console-ops1-api"
APPS_API_URL: Final = "/console/api/v1/apps"


@pytest.fixture(autouse=True)
def _console_superuser_groups(settings: LazySettings) -> None:  # pyright: ignore[reportUnusedFunction]
    settings.EASYAUTH_CONSOLE_SUPERUSER_GROUPS = ("easyauth-admins",)


def test_ops1_apps_api_superuser_lists_all_apps() -> None:
    # Given: 系统管理员面对多个 App。
    client = _logged_in_superuser("ops1-apps-api-admin")
    crm = App.objects.create(app_key="ops1-api-admin-crm", name="CRM")
    erp = App.objects.create(app_key="ops1-api-admin-erp", name="ERP", is_active=False)

    # When: 系统管理员查询 App 列表。
    response = client.get(APPS_API_URL)

    # Then: API 返回全局 App 视图和基础字段。
    assert response.status_code == HTTPStatus.OK
    assert response.json()["data"][0]["app_key"] == crm.app_key
    assert response.json()["data"][0]["name"] == "CRM"
    assert response.json()["data"][0]["description"] == ""
    assert response.json()["data"][0]["is_active"] is True
    assert response.json()["data"][1]["app_key"] == erp.app_key
    assert response.json()["data"][1]["name"] == "ERP"
    assert response.json()["data"][1]["description"] == ""
    assert response.json()["data"][1]["is_active"] is False


def test_ops1_apps_api_allows_non_member_console_user_to_list_apps() -> None:
    # Given: 已登录但没有任何 App 成员关系的普通用户。
    client = _non_admin_client("ops1-apps-api-non-admin")
    app = App.objects.create(app_key="ops1-api-non-admin-crm", name="CRM")

    # When: 该用户查询 App 列表。
    response = client.get(APPS_API_URL)

    # Then: App 目录对控制台登录用户可见, 详情与写操作仍按成员角色控制。
    assert response.status_code == HTTPStatus.OK
    assert app.app_key in response.content.decode()


def test_ops1_apps_api_member_lists_all_apps() -> None:
    # Given: developer 只属于 CRM App, 另一个 ERP App 不属于该用户。
    client = _logged_in_user("ops1-apps-api-developer")
    crm = App.objects.create(app_key="ops1-api-member-crm", name="CRM")
    erp = App.objects.create(app_key="ops1-api-member-erp", name="ERP")
    _ = AppMembership.objects.create(
        app=crm,
        user_id="ops1-apps-api-developer",
        role="developer",
    )

    # When: developer 查询 App 列表。
    response = client.get(APPS_API_URL)

    # Then: API 返回所有 App, 不再按成员关系隐藏。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert crm.app_key in body
    assert erp.app_key in body


def test_ops1_apps_api_superuser_creates_app_with_memberships_and_audit() -> None:
    # Given: 系统管理员提交包含重复和空白成员的 App 创建请求。
    client = _logged_in_superuser("ops1-app-create-admin")

    # When: 系统管理员创建 App。
    response = client.post(
        APPS_API_URL,
        data=dumps(
            {
                "app_key": "ops1-api-create-crm",
                "name": "  CRM  ",
                "description": "客户管理",
                "is_active": False,
                "owner_user_ids": [" owner-a ", "", "owner-a", "shared-user"],
                "developer_user_ids": ["dev-a", " shared-user ", "", "dev-a"],
            },
        ),
        content_type="application/json",
    )

    # Then: API 在同一事务中创建 App、active membership 和审计记录。
    app = App.objects.get(app_key="ops1-api-create-crm")
    owners = list(
        AppMembership.objects.filter(app=app, role="owner", is_active=True)
        .order_by("user_id")
        .values_list("user_id", flat=True),
    )
    developers = list(
        AppMembership.objects.filter(app=app, role="developer", is_active=True)
        .order_by("user_id")
        .values_list("user_id", flat=True),
    )
    body = cast("dict[str, JsonValue]", response.json())
    response_app = cast("dict[str, JsonValue]", body["app"])
    assert response.status_code == HTTPStatus.CREATED
    assert app.name == "CRM"
    assert app.description == "客户管理"
    assert app.is_active is False
    assert owners == ["owner-a", "shared-user"]
    assert developers == ["dev-a"]
    assert response_app["app_key"] == app.app_key
    assert response_app["owners"] == owners
    assert response_app["developers"] == developers
    assert AuditLog.objects.filter(
        actor_id="ops1-app-create-admin",
        event_type="console_app_created",
        target_id=str(app.id),
        metadata__app_key=app.app_key,
        metadata__owner_user_ids=owners,
        metadata__developer_user_ids=developers,
        metadata__is_active=False,
    ).exists()


def test_ops1_apps_api_create_defaults_owner_to_current_actor() -> None:
    # Given: 系统管理员创建 App 时不传 owner。
    client = _logged_in_superuser("ops1-app-create-default-owner")

    # When: 提交最小创建 payload。
    response = client.post(
        APPS_API_URL,
        data=dumps({"app_key": "ops1-api-create-default-owner", "name": "CRM"}),
        content_type="application/json",
    )

    # Then: 当前 actor 自动成为 owner。
    app = App.objects.get(app_key="ops1-api-create-default-owner")
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["app"]["owners"] == ["ops1-app-create-default-owner"]
    assert AppMembership.objects.filter(
        app=app,
        user_id="ops1-app-create-default-owner",
        role="owner",
        is_active=True,
    ).exists()


def test_ops1_apps_api_non_superuser_cannot_create_app() -> None:
    # Given: 普通用户尝试创建 App。
    client = _logged_in_user("ops1-app-create-denied")

    # When: 普通用户提交创建请求。
    response = client.post(
        APPS_API_URL,
        data=dumps({"app_key": "ops1-api-create-denied", "name": "CRM"}),
        content_type="application/json",
    )

    # Then: API 拒绝请求且不落库。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert App.objects.filter(app_key="ops1-api-create-denied").exists() is False


def test_ops1_apps_api_create_rejects_duplicate_app_key() -> None:
    # Given: 已存在同名 app_key。
    client = _logged_in_superuser("ops1-app-create-conflict-admin")
    _ = App.objects.create(app_key="ops1-api-create-conflict", name="CRM")

    # When: 系统管理员重复创建。
    response = client.post(
        APPS_API_URL,
        data=dumps({"app_key": "ops1-api-create-conflict", "name": "CRM 2"}),
        content_type="application/json",
    )

    # Then: API 返回冲突错误。
    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"]["code"] == ErrorCode.CONFLICT


def test_ops1_apps_api_create_rejects_invalid_app_key_and_blank_name() -> None:
    # Given: 系统管理员准备创建 App。
    client = _logged_in_superuser("ops1-app-create-validation-admin")

    # When: app_key 非法或 name 为空。
    invalid_key = client.post(
        APPS_API_URL,
        data=dumps({"app_key": "Invalid Key", "name": "CRM"}),
        content_type="application/json",
    )
    blank_name = client.post(
        APPS_API_URL,
        data=dumps({"app_key": "ops1-api-create-blank-name", "name": "   "}),
        content_type="application/json",
    )

    # Then: API 返回受控校验错误且不落库。
    assert invalid_key.status_code == HTTPStatus.BAD_REQUEST
    assert invalid_key.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert blank_name.status_code == HTTPStatus.BAD_REQUEST
    assert blank_name.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert App.objects.filter(app_key="ops1-api-create-blank-name").exists() is False


def test_ops1_app_detail_api_allows_read_without_membership() -> None:
    # Given: owner 只拥有 CRM App, 不属于 ERP App。
    client = _logged_in_user("ops1-app-detail-api-owner")
    crm = App.objects.create(app_key="ops1-api-detail-crm", name="CRM")
    erp = App.objects.create(app_key="ops1-api-detail-erp", name="ERP")
    _ = AppMembership.objects.create(app=crm, user_id="ops1-app-detail-api-owner", role="owner")

    # When: owner 分别查询所属 App 和未授权 App。
    allowed = client.get(f"{APPS_API_URL}/{crm.app_key}")
    denied = client.get(f"{APPS_API_URL}/{erp.app_key}")

    # Then: 所属 App 和未授权 App 都可读取, 但未授权 App 不可管理。
    assert allowed.status_code == HTTPStatus.OK
    assert allowed.json()["app"]["app_key"] == crm.app_key
    assert allowed.json()["app"]["can_manage"] is True
    assert denied.status_code == HTTPStatus.OK
    assert denied.json()["app"]["app_key"] == erp.app_key
    assert denied.json()["app"]["can_manage"] is False


def test_ops1_apps_api_owner_patches_name_and_description() -> None:
    # Given: owner 可管理一个 CRM App。
    client = _logged_in_user("ops1-app-patch-owner")
    app = App.objects.create(app_key="ops1-api-patch-owner", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="ops1-app-patch-owner", role="owner")

    # When: owner 修改 name 和 description。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"name": "  CRM 新版  ", "description": "更新说明"}),
        content_type="application/json",
    )

    # Then: API 保存允许字段并写审计。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert app.name == "CRM 新版"
    assert app.description == "更新说明"
    assert response.json()["app"]["name"] == "CRM 新版"
    assert AuditLog.objects.filter(
        actor_id="ops1-app-patch-owner",
        event_type="console_app_updated",
        target_id=str(app.id),
        metadata={"name": "CRM 新版", "description": "更新说明"},
    ).exists()


def test_ops1_apps_api_owner_cannot_patch_is_active() -> None:
    # Given: owner 可见 active CRM App。
    client = _logged_in_user("ops1-app-patch-owner-active")
    app = App.objects.create(app_key="ops1-api-patch-owner-active", name="CRM", is_active=True)
    _ = AppMembership.objects.create(app=app, user_id="ops1-app-patch-owner-active", role="owner")

    # When: owner 尝试停用 App。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"is_active": False}),
        content_type="application/json",
    )

    # Then: API 拒绝且数据库状态不变。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert app.is_active is True


def test_ops1_apps_api_superuser_patches_is_active() -> None:
    # Given: 系统管理员面对 active CRM App。
    client = _logged_in_superuser("ops1-app-patch-admin")
    app = App.objects.create(app_key="ops1-api-patch-admin", name="CRM", is_active=True)

    # When: 系统管理员停用 App。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"is_active": False}),
        content_type="application/json",
    )

    # Then: API 保存 is_active 并记录审计变更字段。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert app.is_active is False
    assert response.json()["app"]["is_active"] is False
    assert AuditLog.objects.filter(
        actor_id="ops1-app-patch-admin",
        event_type="console_app_updated",
        target_id=str(app.id),
        metadata={"is_active": False},
    ).exists()


def test_ops1_apps_api_superuser_deletes_app_and_records_audit() -> None:
    # Given: 系统管理员面对一个待删除 App。
    client = _logged_in_superuser("ops1-app-delete-admin")
    app = App.objects.create(app_key="ops1-api-delete", name="Delete Me", is_active=False)
    app_id = app.id

    # When: 系统管理员删除 App。
    response = client.delete(f"{APPS_API_URL}/{app.app_key}")

    # Then: API 硬删除 App, 并在删除前写入审计记录。
    assert response.status_code == HTTPStatus.NO_CONTENT
    assert App.objects.filter(id=app_id).exists() is False
    assert AuditLog.objects.filter(
        actor_id="ops1-app-delete-admin",
        event_type="console_app_deleted",
        target_id=str(app_id),
        metadata__app_key="ops1-api-delete",
        metadata__name="Delete Me",
        metadata__is_active=False,
    ).exists()


def test_ops1_apps_api_non_superuser_cannot_delete_app() -> None:
    # Given: owner 可见一个 App。
    client = _logged_in_user("ops1-app-delete-owner")
    app = App.objects.create(app_key="ops1-api-delete-denied", name="Delete Denied")
    _ = AppMembership.objects.create(app=app, user_id="ops1-app-delete-owner", role="owner")

    # When: owner 尝试删除 App。
    response = client.delete(f"{APPS_API_URL}/{app.app_key}")

    # Then: API 拒绝删除且 App 仍存在。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert app.app_key == "ops1-api-delete-denied"


def test_ops1_apps_api_developer_cannot_patch_app() -> None:
    # Given: developer 可见 CRM App。
    client = _logged_in_user("ops1-app-patch-developer")
    app = App.objects.create(app_key="ops1-api-patch-developer", name="CRM")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-app-patch-developer",
        role="developer",
    )

    # When: developer 尝试修改 App。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"name": "CRM 新版"}),
        content_type="application/json",
    )

    # Then: API 拒绝且数据库不变。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert app.name == "CRM"


def test_ops1_apps_api_patch_rejects_app_key_payload() -> None:
    # Given: 系统管理员面对 CRM App。
    client = _logged_in_superuser("ops1-app-patch-app-key-admin")
    app = App.objects.create(app_key="ops1-api-patch-app-key", name="CRM")

    # When: payload 试图修改 app_key。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}",
        data=dumps({"app_key": "ops1-api-patch-new-key", "name": "CRM 新版"}),
        content_type="application/json",
    )

    # Then: API 返回校验错误且 app_key 不变。
    app.refresh_from_db()
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert app.app_key == "ops1-api-patch-app-key"


def test_ops1_configuration_status_api_uses_app_readiness_service() -> None:
    # Given: developer 可见一个缺少 active 授权目录、owner 和凭据的 App。
    client = _logged_in_user("ops1-app-config-api-developer")
    app = App.objects.create(app_key="ops1-api-config-crm", name="CRM")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-app-config-api-developer",
        role="developer",
    )

    # When: developer 查询配置状态。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/configuration-status")

    # Then: API 返回配置完整性服务计算出的 blocking 状态和风险项。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == "blocking"
    assert "active_permission_missing" in body
    assert "active_authorization_group_missing" in body
    assert "active_owner_missing" in body
    assert "active_credential_missing" in body
    readiness_body = cast("dict[str, JsonValue]", response.json())
    issues = cast("list[dict[str, JsonValue]]", readiness_body["data"])
    assert {
        (issue["code"], issue["target_type"])
        for issue in issues
    } >= {
        ("active_permission_missing", "permission"),
        ("active_authorization_group_missing", "authorization_group"),
        ("active_owner_missing", "membership"),
        ("active_credential_missing", "credential"),
    }


def test_ops1_configuration_status_api_exposes_managed_scope_policy_issue_fields() -> None:
    # Given: App 下 MANAGED_USERS grant 的显式策略已禁用。
    client = _logged_in_superuser("ops1-app-config-managed-owner")
    app = App.objects.create(app_key="ops1-api-config-managed", name="Managed CRM")
    _ = AppMembership.objects.create(app=app, user_id="ops1-app-config-managed-owner", role="owner")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下属")
    permission_group = PermissionGroup.objects.create(app=app, key="CUSTOMER", name="Customer")
    permission = Permission.objects.create(
        app=app,
        group=permission_group,
        key="customer.read",
        name="Read customer",
        supported_scopes=["MANAGED_USERS"],
    )
    authorization_group = AuthorizationGroup.objects.create(
        app=app,
        key="auditor",
        kind="role",
        name="Auditor",
        requestable=True,
    )
    grant = AuthorizationGroupGrant.objects.create(
        authorization_group=authorization_group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=authorization_group,
        approver_userids=["manager-001"],
    )
    _ = StaticTokenService.create_token(app=app, name="token")
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="authorization_group_grant",
        target_id=grant.id,
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
        enabled=False,
    )

    # When: owner 查询配置状态。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/configuration-status")

    # Then: API 暴露 blocking issue 的 subject、target_type、target_id 和中文 message。
    assert response.status_code == HTTPStatus.OK
    body = cast("dict[str, JsonValue]", response.json())
    assert body["status"] == "blocking"
    assert body["data"] == [
        {
            "code": "managed_scope_policy_disabled",
            "severity": "blocking",
            "level": "blocking",
            "message": "MANAGED_USERS grant 的 managed scope policy 已禁用。",
            "subject": "auditor:customer.read:MANAGED_USERS",
            "target_type": "authorization_group_grant",
            "target_id": "auditor:customer.read:MANAGED_USERS",
        },
    ]


def test_ops1_memberships_api_lists_app_memberships_for_visible_app() -> None:
    # Given: developer 可见 CRM App, App 内存在 owner、developer 和停用成员关系。
    client = _logged_in_user("ops1-memberships-api-developer")
    app = App.objects.create(app_key="ops1-api-membership-crm", name="CRM")
    owner = AppMembership.objects.create(app=app, user_id="ops1-membership-owner", role="owner")
    developer = AppMembership.objects.create(
        app=app,
        user_id="ops1-memberships-api-developer",
        role="developer",
    )
    inactive = AppMembership.objects.create(
        app=app,
        user_id="ops1-membership-inactive",
        role="developer",
        is_active=False,
    )

    # When: developer 查询该 App 的成员关系。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/memberships")

    # Then: API 返回可供行操作使用的稳定 membership ID 和 is_active 状态。
    assert response.status_code == HTTPStatus.OK
    assert response.json()["data"] == [
        {
            "id": inactive.id,
            "user_id": "ops1-membership-inactive",
            "role": "developer",
            "is_active": False,
        },
        {
            "id": owner.id,
            "user_id": "ops1-membership-owner",
            "role": "owner",
            "is_active": True,
        },
        {
            "id": developer.id,
            "user_id": "ops1-memberships-api-developer",
            "role": "developer",
            "is_active": True,
        },
    ]


def test_ops1_memberships_api_superuser_creates_developer_membership() -> None:
    # Given: 系统管理员面对一个 CRM App。
    client = _logged_in_superuser("ops1-membership-create-admin-dev")
    app = App.objects.create(app_key="ops1-api-membership-create", name="CRM")

    # When: 系统管理员新增 developer 成员关系。
    response = client.post(
        f"{APPS_API_URL}/{app.app_key}/memberships",
        data=dumps({"user_id": "ops1-membership-new-dev", "role": "developer"}),
        content_type="application/json",
    )

    # Then: API 创建 active developer membership。
    membership = AppMembership.objects.get(app=app, user_id="ops1-membership-new-dev")
    assert response.status_code == HTTPStatus.CREATED
    assert response.json()["membership"] == {
        "id": membership.id,
        "user_id": "ops1-membership-new-dev",
        "role": "developer",
        "is_active": True,
    }
    assert AuditLog.objects.filter(
        actor_id="ops1-membership-create-admin-dev",
        event_type="console_app_membership_created",
        target_id=str(membership.id),
        metadata__app_key=app.app_key,
    ).exists()


def test_ops1_memberships_api_superuser_creates_owner_membership() -> None:
    # Given: 系统管理员面对一个没有自身 membership 的 CRM App。
    client = _logged_in_superuser("ops1-membership-create-admin")
    app = App.objects.create(app_key="ops1-api-membership-admin-create", name="CRM")

    # When: 系统管理员新增 owner 成员关系。
    response = client.post(
        f"{APPS_API_URL}/{app.app_key}/memberships",
        data=dumps({"user_id": "ops1-membership-new-owner", "role": "owner"}),
        content_type="application/json",
    )

    # Then: API 允许系统管理员创建 owner membership。
    assert response.status_code == HTTPStatus.CREATED
    assert AppMembership.objects.filter(
        app=app,
        user_id="ops1-membership-new-owner",
        role="owner",
        is_active=True,
    ).exists()


def test_ops1_memberships_api_superuser_patches_role_and_active_state() -> None:
    # Given: 系统管理员面对一个已有 developer membership 的 CRM App。
    client = _logged_in_superuser("ops1-membership-patch-admin")
    app = App.objects.create(app_key="ops1-api-membership-patch", name="CRM")
    membership = AppMembership.objects.create(
        app=app,
        user_id="ops1-membership-patch-target",
        role="developer",
    )

    # When: 系统管理员将该 membership 调整为 inactive owner。
    response = client.patch(
        f"{APPS_API_URL}/{app.app_key}/memberships/{membership.id}",
        data=dumps({"role": "owner", "is_active": False}),
        content_type="application/json",
    )

    # Then: API 保存 role 和 is_active 的修改。
    membership.refresh_from_db()
    assert response.status_code == HTTPStatus.OK
    assert response.json()["membership"] == {
        "id": membership.id,
        "user_id": "ops1-membership-patch-target",
        "role": "owner",
        "is_active": False,
    }
    assert AuditLog.objects.filter(
        actor_id="ops1-membership-patch-admin",
        event_type="console_app_membership_updated",
        target_id=str(membership.id),
        metadata__is_active=False,
    ).exists()


def test_ops1_memberships_api_developer_cannot_write_memberships() -> None:
    # Given: developer 可见 CRM App 但没有管理权限。
    client = _logged_in_user("ops1-membership-write-dev")
    app = App.objects.create(app_key="ops1-api-membership-dev-write", name="CRM")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-membership-write-dev",
        role="developer",
    )

    # When: developer 尝试新增 membership。
    response = client.post(
        f"{APPS_API_URL}/{app.app_key}/memberships",
        data=dumps({"user_id": "ops1-membership-forbidden", "role": "developer"}),
        content_type="application/json",
    )

    # Then: API 拒绝 developer 写入且没有落库。
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert AppMembership.objects.filter(user_id="ops1-membership-forbidden").exists() is False


def test_ops1_memberships_api_owner_cannot_patch_membership_from_other_app() -> None:
    # Given: 系统管理员面对 CRM App, 但目标 membership 属于 ERP App。
    client = _logged_in_superuser("ops1-membership-cross-app-admin")
    crm = App.objects.create(app_key="ops1-api-membership-cross-crm", name="CRM")
    erp = App.objects.create(app_key="ops1-api-membership-cross-erp", name="ERP")
    erp_membership = AppMembership.objects.create(
        app=erp,
        user_id="ops1-membership-cross-target",
        role="developer",
    )

    # When: 系统管理员使用 CRM 路径修改 ERP membership。
    response = client.patch(
        f"{APPS_API_URL}/{crm.app_key}/memberships/{erp_membership.id}",
        data=dumps({"is_active": False}),
        content_type="application/json",
    )

    # Then: API 按当前 App 查找 membership, 不跨 App 修改。
    erp_membership.refresh_from_db()
    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"]["code"] == ErrorCode.NOT_FOUND
    assert erp_membership.is_active is True


def test_ops1_memberships_api_duplicate_active_membership_returns_conflict() -> None:
    # Given: CRM App 已存在 active developer membership。
    client = _logged_in_superuser("ops1-membership-conflict-admin")
    app = App.objects.create(app_key="ops1-api-membership-conflict", name="CRM")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-membership-conflict-user",
        role="developer",
    )

    # When: 系统管理员再次创建相同 active membership。
    response = client.post(
        f"{APPS_API_URL}/{app.app_key}/memberships",
        data=dumps({"user_id": "ops1-membership-conflict-user", "role": "developer"}),
        content_type="application/json",
    )

    # Then: API 返回受控 409 冲突。
    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"]["code"] == ErrorCode.CONFLICT


def test_ops1_apps_api_rejects_anonymous_user() -> None:
    # Given: 未登录 client。
    client = Client(HTTP_HOST="localhost")

    # When: 未登录用户查询 App 列表。
    response = client.get(APPS_API_URL)

    # Then: API 返回统一认证错误。
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["error"]["code"] == ErrorCode.AUTHENTICATION_FAILED


def test_ops1_configuration_status_api_can_return_ready_status() -> None:
    # Given: owner 可见一个具备 active 授权目录和 active 凭据的 App。
    client = _logged_in_user("ops1-config-ready-owner")
    app = App.objects.create(app_key="ops1-api-config-ready", name="Ready CRM")
    _ = AppMembership.objects.create(app=app, user_id="ops1-config-ready-owner", role="owner")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="Global")
    permission_group = PermissionGroup.objects.create(app=app, key="CUSTOMER", name="Customer")
    permission = Permission.objects.create(
        app=app,
        group=permission_group,
        key="customer.read",
        name="Read customer",
        supported_scopes=["GLOBAL"],
    )
    authorization_group = AuthorizationGroup.objects.create(
        app=app,
        key="auditor",
        kind="role",
        name="Auditor",
        requestable=True,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=authorization_group,
        permission=permission,
        scope_key="GLOBAL",
    )
    _ = ApprovalRule.objects.create(
        app=app,
        authorization_group=authorization_group,
        approver_userids=["manager-001"],
    )
    _ = StaticTokenService.create_token(app=app, name="token")

    # When: owner 查询配置状态。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/configuration-status")

    # Then: API 返回 ready 状态且没有风险项。
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"app_key": app.app_key, "status": "ready", "data": []}


def _logged_in_superuser(username: str) -> Client:
    return _authentik_client(username, groups=("easyauth-admins",))


def _logged_in_user(username: str) -> Client:
    return _authentik_client(username)


def _authentik_client(username: str, *, groups: tuple[str, ...] = ()) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    if groups:
        session[AUTHENTIK_GROUPS_SESSION_KEY] = list(groups)
    session.save()
    return client


def _non_admin_client(username: str) -> Client:
    user, _created = UserMirror.objects.get_or_create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = user.authentik_user_id
    session.save()
    return client

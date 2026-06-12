from __future__ import annotations

from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final

import pytest
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import UserMirror
from easyauth.api.errors import ErrorCode
from easyauth.applications.models import App, AppMembership, Role
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
    assert response.json()["items"][0]["app_key"] == crm.app_key
    assert response.json()["items"][0]["name"] == "CRM"
    assert response.json()["items"][0]["description"] == ""
    assert response.json()["items"][0]["is_active"] is True
    assert response.json()["items"][1]["app_key"] == erp.app_key
    assert response.json()["items"][1]["name"] == "ERP"
    assert response.json()["items"][1]["description"] == ""
    assert response.json()["items"][1]["is_active"] is False


def test_ops1_apps_api_member_lists_only_visible_apps() -> None:
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

    # Then: API 只返回该用户可见的 App。
    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert crm.app_key in body
    assert erp.app_key not in body


def test_ops1_app_detail_api_requires_visible_membership() -> None:
    # Given: owner 只拥有 CRM App, 不属于 ERP App。
    client = _logged_in_user("ops1-app-detail-api-owner")
    crm = App.objects.create(app_key="ops1-api-detail-crm", name="CRM")
    erp = App.objects.create(app_key="ops1-api-detail-erp", name="ERP")
    _ = AppMembership.objects.create(app=crm, user_id="ops1-app-detail-api-owner", role="owner")

    # When: owner 分别查询所属 App 和未授权 App。
    allowed = client.get(f"{APPS_API_URL}/{crm.app_key}")
    denied = client.get(f"{APPS_API_URL}/{erp.app_key}")

    # Then: 所属 App 返回详情, 未授权 App 按不存在处理。
    assert allowed.status_code == HTTPStatus.OK
    assert allowed.json()["app"]["app_key"] == crm.app_key
    assert allowed.json()["app"]["can_manage"] is True
    assert denied.status_code == HTTPStatus.NOT_FOUND
    assert denied.json()["error"]["code"] == ErrorCode.NOT_FOUND


def test_ops1_configuration_status_api_uses_app_readiness_service() -> None:
    # Given: developer 可见一个缺少 active Role 和凭据的 App。
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
    assert "active_role_missing" in body
    assert "active_credential_missing" in body


def test_ops1_memberships_api_lists_app_memberships_for_visible_app() -> None:
    # Given: developer 可见 CRM App, App 内存在 owner、developer 和停用成员关系。
    client = _logged_in_user("ops1-memberships-api-developer")
    app = App.objects.create(app_key="ops1-api-membership-crm", name="CRM")
    _ = AppMembership.objects.create(app=app, user_id="ops1-membership-owner", role="owner")
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-memberships-api-developer",
        role="developer",
    )
    _ = AppMembership.objects.create(
        app=app,
        user_id="ops1-membership-inactive",
        role="developer",
        is_active=False,
    )

    # When: developer 查询该 App 的成员关系。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/memberships")

    # Then: API 返回该 App 的成员关系并暴露 is_active 状态。
    assert response.status_code == HTTPStatus.OK
    assert response.json()["items"] == [
        {"user_id": "ops1-membership-inactive", "role": "developer", "is_active": False},
        {"user_id": "ops1-membership-owner", "role": "owner", "is_active": True},
        {"user_id": "ops1-memberships-api-developer", "role": "developer", "is_active": True},
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
    # Given: owner 可见一个具备 active Role 和 active 凭据的 App。
    client = _logged_in_user("ops1-config-ready-owner")
    app = App.objects.create(app_key="ops1-api-config-ready", name="Ready CRM")
    _ = AppMembership.objects.create(app=app, user_id="ops1-config-ready-owner", role="owner")
    _ = Role.objects.create(app=app, key="auditor", name="Auditor", requestable=False)
    _ = StaticTokenService.create_token(app=app, name="token")

    # When: owner 查询配置状态。
    response = client.get(f"{APPS_API_URL}/{app.app_key}/configuration-status")

    # Then: API 返回 ready 状态且没有风险项。
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"app_key": app.app_key, "status": "ready", "issues": [], "items": []}


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
        session["easyauth_authentik_groups"] = list(groups)
    session.save()
    return client

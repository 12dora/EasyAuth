from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from json import dumps
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.test import Client
from django.utils import timezone

from easyauth.accounts.models import USER_STATUS_DISABLED, UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    Permission,
)
from easyauth.audit.models import AuditLog
from easyauth.grants.direct_grant import DIRECT_GRANT_APPLIED_ACTION
from easyauth.grants.managed_users import MANAGED_USERS_DIRECTORY_UNAVAILABLE_MESSAGE
from easyauth.grants.models import (
    MEMBERSHIP_SOURCE_DEPARTMENT,
    MEMBERSHIP_SOURCE_USER,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)
from easyauth.integrations.authentik.directory_client import AuthentikDirectoryUnavailableError
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue
    from easyauth.integrations.authentik.directory_payloads import DingTalkManagedUsers

pytestmark = pytest.mark.django_db

DIRECT_GRANTS_API_URL: Final = "/console/api/v1/direct-grants"


def test_direct_grants_requires_authentication() -> None:
    client = Client(HTTP_HOST="localhost")

    response = client.post(DIRECT_GRANTS_API_URL, data="{}", content_type="application/json")

    assert response.status_code == HTTPStatus.UNAUTHORIZED


def test_direct_grants_requires_superuser() -> None:
    client = _logged_in_user("direct-grant-ordinary")

    response = client.post(DIRECT_GRANTS_API_URL, data="{}", content_type="application/json")

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_direct_grants_rejects_unknown_user_and_inactive_user() -> None:
    client = _logged_in_superuser("direct-grant-lookup-admin")
    app, group, _permission = _catalog("direct-grant-lookup")
    departed = UserMirror.objects.create(
        authentik_user_id="direct-grant-departed",
        status=USER_STATUS_DISABLED,
    )

    missing = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_payload(user_id="missing-user", app_key=app.app_key, groups=[group.key])),
        content_type="application/json",
    )
    inactive = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(user_id=departed.authentik_user_id, app_key=app.app_key, groups=[group.key]),
        ),
        content_type="application/json",
    )
    unknown_app = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id="direct-grant-lookup-admin",
                app_key="missing-app",
                groups=[group.key],
            ),
        ),
        content_type="application/json",
    )

    assert missing.status_code == HTTPStatus.NOT_FOUND
    assert missing.json()["error"]["code"] == "NOT_FOUND"
    assert inactive.status_code == HTTPStatus.CONFLICT
    assert inactive.json()["error"]["code"] == "CONFLICT"
    assert unknown_app.status_code == HTTPStatus.NOT_FOUND
    assert unknown_app.json()["error"]["code"] == "NOT_FOUND"


def test_direct_grants_returns_chinese_semantic_errors() -> None:
    client = _logged_in_superuser("direct-grant-validate-admin")
    app, _group, permission = _catalog("direct-grant-validate")
    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="inactive",
        kind="role",
        name="停用角色",
        is_active=False,
    )
    user = UserMirror.objects.create(authentik_user_id="direct-grant-validate-user")

    empty = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(_payload(user_id=user.authentik_user_id, app_key=app.app_key)),
        content_type="application/json",
    )
    inactive = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id=user.authentik_user_id,
                app_key=app.app_key,
                groups=[inactive_group.key],
            ),
        ),
        content_type="application/json",
    )
    unsupported_scope = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id=user.authentik_user_id,
                app_key=app.app_key,
                directs=[{"permission": permission.key, "scope": "TEAM"}],
            ),
        ),
        content_type="application/json",
    )

    assert empty.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert empty.json()["error"]["code"] == "SEMANTIC_VALIDATION_ERROR"
    assert "至少选择一个授权组或权限" in empty.json()["error"]["details"]["errors"][0]
    assert inactive.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "授权组未启用" in inactive.json()["error"]["details"]["errors"][0]
    assert unsupported_scope.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "不支持指定的授权范围" in unsupported_scope.json()["error"]["details"]["errors"][0]


def test_direct_grants_merges_groups_replaces_expiry_and_keeps_department_rows() -> None:
    client = _logged_in_superuser("direct-grant-merge-admin")
    app, sales, permission = _catalog("direct-grant-merge")
    finance = AuthorizationGroup.objects.create(
        app=app,
        key="finance",
        kind="role",
        name="财务",
        requestable=False,
    )
    user = UserMirror.objects.create(authentik_user_id="direct-grant-merge-user")
    first_expiry = (timezone.now() + timedelta(days=10)).replace(microsecond=0)
    second_expiry = (timezone.now() + timedelta(days=40)).replace(microsecond=0)

    first = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id=user.authentik_user_id,
                app_key=app.app_key,
                groups=[sales.key],
                grant_type="timed",
                grant_expires_at=_json_datetime(first_expiry),
            ),
        ),
        content_type="application/json",
    )
    grant_id = first.json()["data"]["grant"]["id"]
    grant = AccessGrant.objects.get(pk=grant_id)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=finance,
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="GLOBAL",
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
    )

    second = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id=user.authentik_user_id,
                app_key=app.app_key,
                groups=[finance.key],
                grant_type="timed",
                grant_expires_at=_json_datetime(second_expiry),
            ),
        ),
        content_type="application/json",
    )
    replaced = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id=user.authentik_user_id,
                app_key=app.app_key,
                groups=[sales.key],
                grant_type="timed",
                grant_expires_at=_json_datetime(second_expiry),
                reason="续期销售授权",
            ),
        ),
        content_type="application/json",
    )

    grant.refresh_from_db()
    user_groups = list(
        AccessGrantGroup.objects.filter(grant=grant, source=MEMBERSHIP_SOURCE_USER).values_list(
            "authorization_group__key",
            "expires_at",
        ),
    )
    department_groups = list(
        AccessGrantGroup.objects.filter(
            grant=grant, source=MEMBERSHIP_SOURCE_DEPARTMENT
        ).values_list(
            "authorization_group__key",
            flat=True,
        ),
    )
    second_body = cast("dict[str, JsonValue]", second.json()["data"])
    replaced_body = cast("dict[str, JsonValue]", replaced.json()["data"])
    assert first.status_code == HTTPStatus.CREATED
    assert first.json()["data"]["grant"]["version"] == 1
    assert second.status_code == HTTPStatus.CREATED
    assert second_body["grant"]["version"] == 2
    assert {
        item["key"]
        for item in second_body["grant"]["authorization_groups"]
        if item["source"] == MEMBERSHIP_SOURCE_USER
    } == {sales.key, finance.key}
    assert replaced.status_code == HTTPStatus.CREATED
    assert replaced_body["grant"]["version"] == 3
    assert grant.version == 3
    sales_expiry = next(expires_at for key, expires_at in user_groups if key == sales.key)
    finance_expiry = next(expires_at for key, expires_at in user_groups if key == finance.key)
    assert sales_expiry == second_expiry
    assert finance_expiry == second_expiry
    assert department_groups == [finance.key]
    assert AccessGrantPermission.objects.filter(
        grant=grant,
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
        permission=permission,
    ).exists()
    audit = (
        AuditLog.objects.filter(event_type=DIRECT_GRANT_APPLIED_ACTION, target_id=str(grant.id))
        .order_by("-id")
        .first()
    )
    assert audit is not None
    assert audit.actor_type == "admin"
    assert audit.metadata["reason"] == "续期销售授权"
    assert AuditLog.objects.filter(event_type=DIRECT_GRANT_APPLIED_ACTION).count() == 3


def test_direct_grants_persists_groups_not_expanded_permissions() -> None:
    client = _logged_in_superuser("direct-grant-shape-admin")
    app, group, permission = _catalog("direct-grant-shape")
    user = UserMirror.objects.create(authentik_user_id="direct-grant-shape-user")

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id=user.authentik_user_id,
                app_key=app.app_key,
                groups=[group.key],
                directs=[{"permission": permission.key, "scope": "GLOBAL"}],
            ),
        ),
        content_type="application/json",
    )

    payload = response.json()["data"]["grant"]
    grant = AccessGrant.objects.get(pk=payload["id"])
    assert response.status_code == HTTPStatus.CREATED
    assert payload["authorization_groups"] == [
        {
            "key": group.key,
            "kind": "role",
            "name": "销售",
            "expires_at": None,
            "source": MEMBERSHIP_SOURCE_USER,
        },
    ]
    assert payload["direct_grants"] == [
        {
            "permission": permission.key,
            "permission_name": permission.name,
            "scope": "GLOBAL",
            "scope_name": "全局",
            "expires_at": None,
            "source": MEMBERSHIP_SOURCE_USER,
        },
    ]
    assert AccessGrantGroup.objects.filter(
        grant=grant,
        source=MEMBERSHIP_SOURCE_USER,
        authorization_group=group,
    ).exists()
    assert AccessGrantPermission.objects.filter(
        grant=grant,
        source=MEMBERSHIP_SOURCE_USER,
        permission=permission,
        scope_key="GLOBAL",
    ).exists()


class _UnavailableManagedUsersClient:
    def get_managed_users(self, corp_id: str, manager_user_id: str) -> DingTalkManagedUsers:
        _ = corp_id, manager_user_id
        message = "目录不可用"
        raise AuthentikDirectoryUnavailableError(message)


def test_direct_grants_rolls_back_when_directory_unavailable_for_managed_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _logged_in_superuser("direct-grant-directory-admin")
    user = UserMirror.objects.create(
        authentik_user_id="direct-grant-directory-user",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="manager-dt",
    )
    app = App.objects.create(app_key="direct-grant-directory-app", name="CRM")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="管理范围")
    permission = Permission.objects.create(
        app=app,
        key="customer.profile.view",
        name="查看客户",
        supported_scopes=["MANAGED_USERS"],
    )
    group = AuthorizationGroup.objects.create(
        app=app,
        key="team-manager",
        kind="role",
        name="主管",
        requestable=False,
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="MANAGED_USERS",
    )
    _ = ManagedScopePolicy.objects.create(
        app=app,
        target_type="app_default",
        scope="MANAGED_USERS",
        resolver="dingtalk_manager_chain",
    )
    monkeypatch.setattr(
        "easyauth.grants.managed_users.AuthentikDirectoryClient.from_settings",
        lambda: _UnavailableManagedUsersClient(),
    )

    response = client.post(
        DIRECT_GRANTS_API_URL,
        data=dumps(
            _payload(
                user_id=user.authentik_user_id,
                app_key=app.app_key,
                groups=[group.key],
            ),
        ),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json()["error"] == {
        "code": "DEPENDENCY_UNAVAILABLE",
        "message": MANAGED_USERS_DIRECTORY_UNAVAILABLE_MESSAGE,
        "details": {},
    }
    assert AccessGrant.objects.filter(user=user, app=app).count() == 0
    assert AuditLog.objects.filter(event_type=DIRECT_GRANT_APPLIED_ACTION).count() == 0


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
    return app, group, permission


def _payload(  # noqa: PLR0913 - 测试载荷构造需要显式覆盖各字段。
    *,
    user_id: str,
    app_key: str,
    groups: list[str] | None = None,
    directs: list[dict[str, str]] | None = None,
    grant_type: str = "permanent",
    grant_expires_at: str | None = None,
    reason: str = "管理员直接授权",
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "app_key": app_key,
        "authorization_group_keys": groups or [],
        "direct_grants": directs or [],
        "grant_type": grant_type,
        "grant_expires_at": grant_expires_at,
        "reason": reason,
    }


def _json_datetime(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _logged_in_user(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    authenticate_console_user(client, username)
    return client


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    authenticate_console_admin(client, username)
    return client

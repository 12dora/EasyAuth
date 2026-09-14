from __future__ import annotations

from http import HTTPStatus
from json import loads
from typing import TYPE_CHECKING, final
from urllib.error import URLError

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from easyauth.accounts.authentik_provisioning import USER_PROVISION_UNAVAILABLE_MESSAGE
from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror, UserMirror
from easyauth.api.views import query_user_permissions
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.applications.services import AppPrincipal
from easyauth.audit.models import AuditLog
from easyauth.grants.models import (
    DepartmentGrantPolicy,
    DepartmentGrantPolicyGroup,
    DepartmentGrantPolicyPermission,
)
from easyauth.grants.query import (
    ExpandedGrant,
    PermissionSnapshot,
    ResolvedManagedUsers,
)
from easyauth.integrations.authentik.admin_client import AuthentikAdminUserNotFoundError

if TYPE_CHECKING:
    from easyauth.integrations.authentik.admin_client import AdminJson

pytestmark = pytest.mark.django_db

_JIT_SUB = "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"
_JIT_SOURCE = "dingtalk"
_JIT_CORP = "dingtalk-corp"
_JIT_USER = "user-chenning"
_JIT_DEPT = "990739069"
_JIT_GROUP_KEY = "easycustoms:customs-viewer"
_UNAVAILABLE_CACHE_KEY = "authentik-provision-unavailable"


def test_permission_query_view_serializes_managed_users(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 公共权限查询返回包含 MANAGED_USERS resolved 的快照。
    app = App.objects.create(app_key="crm-api-managed-users", name="CRM")
    snapshot = PermissionSnapshot(
        user_id="alice",
        app_key=app.app_key,
        groups=(),
        grants=(
            ExpandedGrant(
                permission="customer.profile.view",
                scope="MANAGED_USERS",
                source_type="group",
                source_key="team-manager",
                expires_at=None,
                resolved=ResolvedManagedUsers(
                    user_ids=("bob", "carol"),
                    resolver="dingtalk_manager_chain",
                    resolved_at="2026-07-02T12:00:00+08:00",
                ),
            ),
        ),
        grant_version=2,
        catalog_version=3,
        snapshot_version="2.3",
    )
    monkeypatch.setattr(
        "easyauth.api.views.authenticate_permission_query_token",
        lambda _token: AppPrincipal(
            app_id=app.id,
            app_key=app.app_key,
            credential_type="static_token",
            credential_id=1,
        ),
    )
    monkeypatch.setattr("easyauth.api.views.resolve_user_permissions", lambda **_kwargs: snapshot)
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer eat_test")

    # When: 应用查询该用户权限。
    response = query_user_permissions(request, app.app_key, "alice")

    # Then: JSON 响应保留 resolved 结构。
    payload = loads(response.content)
    assert response.status_code == HTTPStatus.OK
    assert payload["grants"] == [
        {
            "permission": "customer.profile.view",
            "scope": "MANAGED_USERS",
            "source_type": "group",
            "source_key": "team-manager",
            "resolved": {
                "user_ids": ["bob", "carol"],
                "resolver": "dingtalk_manager_chain",
                "resolved_at": "2026-07-02T12:00:00+08:00",
            },
        },
    ]


@final
class _JitAdminClient:
    def __init__(self, entry: AdminJson) -> None:
        self.entry = entry
        self.get_user_calls = 0

    def get_user_by_uuid(self, sub: str) -> AdminJson:
        self.get_user_calls += 1
        assert sub == self.entry["uuid"]
        return self.entry


def _jit_core_user() -> AdminJson:
    return {
        "pk": 7,
        "name": "陈柠",
        "is_active": True,
        "email": "",
        "uuid": _JIT_SUB,
        "attributes": {
            "dingtalk": {
                "name": "陈柠",
                "corp_id": _JIT_CORP,
                "user_id": _JIT_USER,
                "source_slug": _JIT_SOURCE,
                "job_number": "",
            },
        },
    }


def _seed_department_grant(app: App) -> AuthorizationGroup:
    AppScope.objects.get_or_create(app=app, key="GLOBAL", defaults={"name": "全局"})
    group = AuthorizationGroup.objects.create(
        app=app,
        key=_JIT_GROUP_KEY,
        name="报关只读",
        kind="role",
    )
    permission = Permission.objects.create(
        app=app,
        key="customs.read",
        name="读取",
        supported_scopes=["GLOBAL"],
    )
    DingTalkDepartmentMirror.objects.create(
        source_slug=_JIT_SOURCE,
        corp_id=_JIT_CORP,
        dept_id=_JIT_DEPT,
        parent_id="",
        name="外贸部",
    )
    policy = DepartmentGrantPolicy.objects.create(
        source_slug=_JIT_SOURCE,
        corp_id=_JIT_CORP,
        dept_id=_JIT_DEPT,
        app=app,
        grant_type="permanent",
        reason="部门策略",
        created_by_type="admin",
        created_by_id="admin",
        updated_by_type="admin",
        updated_by_id="admin",
    )
    DepartmentGrantPolicyGroup.objects.create(policy=policy, authorization_group=group)
    DepartmentGrantPolicyPermission.objects.create(
        policy=policy,
        permission=permission,
        scope_key="GLOBAL",
    )
    _ = DingTalkUserMirror.objects.create(
        source_slug=_JIT_SOURCE,
        corp_id=_JIT_CORP,
        user_id=_JIT_USER,
        status="active",
        department_ids=[_JIT_DEPT],
    )
    return group


def _principal_for(app: App) -> AppPrincipal:
    return AppPrincipal(
        app_id=app.id,
        app_key=app.app_key,
        credential_type="static_token",
        credential_id=1,
    )


def test_permission_query_jit_creates_mirror_for_unknown_directory_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    app = App.objects.create(app_key="easycustoms-jit", name="EasyCustoms")
    group = _seed_department_grant(app)
    client = _JitAdminClient(_jit_core_user())
    monkeypatch.setattr(
        "easyauth.api.views.authenticate_permission_query_token",
        lambda _token: _principal_for(app),
    )
    monkeypatch.setattr(
        "easyauth.accounts.authentik_provisioning.AuthentikAdminClient.from_settings",
        lambda: client,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer eat_test")

    response = query_user_permissions(request, app.app_key, _JIT_SUB)

    payload = loads(response.content)
    assert response.status_code == HTTPStatus.OK
    user = UserMirror.objects.get(authentik_user_id=_JIT_SUB)
    assert user.name == "陈柠"
    assert user.dingtalk_userid == _JIT_USER
    assert user.dingtalk_corp_id == _JIT_CORP
    assert user.dingtalk_source_slug == _JIT_SOURCE
    assert payload["user_id"] == _JIT_SUB
    assert payload["groups"] == [{"key": group.key, "kind": group.kind, "name": group.name}]
    audit = AuditLog.objects.get(event_type="app_permission_queried")
    assert audit.metadata["provisioned"] is True
    assert client.get_user_calls == 1


def test_permission_query_jit_skips_existing_mirror(monkeypatch: pytest.MonkeyPatch) -> None:
    app = App.objects.create(app_key="easycustoms-jit-existing", name="EasyCustoms")
    _ = UserMirror.objects.create(authentik_user_id=_JIT_SUB, name="已有")
    client = _JitAdminClient(_jit_core_user())
    monkeypatch.setattr(
        "easyauth.api.views.authenticate_permission_query_token",
        lambda _token: _principal_for(app),
    )
    monkeypatch.setattr(
        "easyauth.accounts.authentik_provisioning.AuthentikAdminClient.from_settings",
        lambda: client,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer eat_test")

    response = query_user_permissions(request, app.app_key, _JIT_SUB)

    assert response.status_code == HTTPStatus.OK
    assert client.get_user_calls == 0
    audit = AuditLog.objects.get(event_type="app_permission_queried")
    assert "provisioned" not in audit.metadata
    assert UserMirror.objects.get(authentik_user_id=_JIT_SUB).name == "已有"


@final
class _JitErrorClient:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.get_user_calls = 0

    def get_user_by_uuid(self, sub: str) -> AdminJson:
        self.get_user_calls += 1
        del sub
        raise self.error


def test_permission_query_malformed_core_user_returns_empty_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    cache.clear()
    app = App.objects.create(app_key="easycustoms-jit-invalid", name="EasyCustoms")
    client = _JitAdminClient(
        {
            "uuid": _JIT_SUB,
            "is_active": True,
            "attributes": {"dingtalk": "not-object"},
        },
    )
    monkeypatch.setattr(
        "easyauth.api.views.authenticate_permission_query_token",
        lambda _token: _principal_for(app),
    )
    monkeypatch.setattr(
        "easyauth.accounts.authentik_provisioning.AuthentikAdminClient.from_settings",
        lambda: client,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer eat_test")

    with caplog.at_level("ERROR"):
        response = query_user_permissions(request, app.app_key, _JIT_SUB)

    payload = loads(response.content)
    assert response.status_code == HTTPStatus.OK
    assert payload["groups"] == []
    assert payload["grants"] == []
    assert not UserMirror.objects.filter(authentik_user_id=_JIT_SUB).exists()
    assert _JIT_SUB in caplog.text
    assert cache.get(f"authentik-provision-miss:{_JIT_SUB}") == 1


def test_permission_query_transient_authentik_failure_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    app = App.objects.create(app_key="easycustoms-jit-503", name="EasyCustoms")
    client = _JitErrorClient(URLError("timed out"))
    monkeypatch.setattr(
        "easyauth.api.views.authenticate_permission_query_token",
        lambda _token: _principal_for(app),
    )
    monkeypatch.setattr(
        "easyauth.accounts.authentik_provisioning.AuthentikAdminClient.from_settings",
        lambda: client,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer eat_test")

    response = query_user_permissions(request, app.app_key, _JIT_SUB)

    payload = loads(response.content)
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert payload["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
    assert payload["error"]["message"] == USER_PROVISION_UNAVAILABLE_MESSAGE
    assert cache.get(_UNAVAILABLE_CACHE_KEY) == 1
    assert client.get_user_calls == 1

    second = query_user_permissions(request, app.app_key, "another-unknown-sub")
    assert second.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert client.get_user_calls == 1


def test_permission_query_unknown_authentik_user_returns_empty_and_negative_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache.clear()
    app = App.objects.create(app_key="easycustoms-jit-miss", name="EasyCustoms")
    client = _JitErrorClient(AuthentikAdminUserNotFoundError())
    monkeypatch.setattr(
        "easyauth.api.views.authenticate_permission_query_token",
        lambda _token: _principal_for(app),
    )
    monkeypatch.setattr(
        "easyauth.accounts.authentik_provisioning.AuthentikAdminClient.from_settings",
        lambda: client,
    )
    request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer eat_test")

    response = query_user_permissions(request, app.app_key, _JIT_SUB)

    payload = loads(response.content)
    assert response.status_code == HTTPStatus.OK
    assert payload["groups"] == []
    assert payload["grants"] == []
    assert cache.get(f"authentik-provision-miss:{_JIT_SUB}") == 1
    assert cache.get(_UNAVAILABLE_CACHE_KEY) is None
    assert client.get_user_calls == 1

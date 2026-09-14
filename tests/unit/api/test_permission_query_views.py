from __future__ import annotations

from http import HTTPStatus
from json import loads
from typing import TYPE_CHECKING, final

import pytest
from django.test import RequestFactory

from easyauth.accounts.models import UserMirror
from easyauth.api.views import query_user_permissions
from easyauth.applications.models import App
from easyauth.applications.services import AppPrincipal
from easyauth.audit.models import AuditLog
from easyauth.grants.query import (
    ExpandedGrant,
    PermissionSnapshot,
    ResolvedManagedUsers,
)

if TYPE_CHECKING:
    from easyauth.integrations.authentik.admin_client import AdminJson

pytestmark = pytest.mark.django_db

_JIT_SUB = "fdac7e94-a7ab-4311-9b57-436f3a35f3cb"


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
                "corp_id": "dingtalk-corp",
                "user_id": "user-chenning",
                "source_slug": "dingtalk",
                "job_number": "",
            },
        },
    }


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
    app = App.objects.create(app_key="easycustoms-jit", name="EasyCustoms")
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
    assert user.dingtalk_userid == "user-chenning"
    assert user.dingtalk_corp_id == "dingtalk-corp"
    assert user.dingtalk_source_slug == "dingtalk"
    assert payload["user_id"] == _JIT_SUB
    assert payload["groups"] == []
    assert payload["grants"] == []
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

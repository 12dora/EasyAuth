from __future__ import annotations

from http import HTTPStatus
from json import loads

import pytest
from django.test import RequestFactory

from easyauth.api.views import query_user_permissions
from easyauth.applications.models import App
from easyauth.applications.services import AppPrincipal
from easyauth.grants.query import (
    ExpandedGrant,
    PermissionSnapshot,
    ResolvedManagedUsers,
)

pytestmark = pytest.mark.django_db


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

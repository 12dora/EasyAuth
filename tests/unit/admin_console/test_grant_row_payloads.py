from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.admin_console.grant_row_payloads import serialize_access_grant_row
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import (
    MEMBERSHIP_SOURCE_DEPARTMENT,
    MEMBERSHIP_SOURCE_USER,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

pytestmark = pytest.mark.django_db


def test_serialize_access_grant_row_includes_names_sources_and_expansion() -> None:
    user = UserMirror.objects.create(authentik_user_id="grant-row-user", name="胡玉琴A")
    app = App.objects.create(
        app_key="easylearning",
        name="EasyLearning",
        alias="学习工作台",
    )
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    group = AuthorizationGroup.objects.create(app=app, key="sales", kind="role", name="销售")
    permission = Permission.objects.create(
        app=app,
        key="order.order.view",
        name="查看订单",
        supported_scopes=["GLOBAL"],
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=permission,
        scope_key="GLOBAL",
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    expires_at = timezone.now() + timedelta(days=7)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=expires_at,
        source=MEMBERSHIP_SOURCE_USER,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="GLOBAL",
        expires_at=None,
        source=MEMBERSHIP_SOURCE_DEPARTMENT,
    )

    row = serialize_access_grant_row(grant)

    assert row["id"] == grant.id
    assert row["version"] == 1
    assert row["is_current"] is True
    assert row["status"] == "active"
    assert row["user_id"] == "grant-row-user"
    assert row["user_name"] == "胡玉琴A"
    assert row["app_key"] == "easylearning"
    assert row["app_name"] == "EasyLearning"
    assert row["app_alias"] == "学习工作台"
    assert row["grant_type"] == "mixed"
    assert row["grant_expires_at"] == expires_at.isoformat()
    assert row["authorization_groups"] == [
        {
            "key": "sales",
            "kind": "role",
            "name": "销售",
            "expires_at": expires_at.isoformat(),
            "source": MEMBERSHIP_SOURCE_USER,
        },
    ]
    assert row["direct_grants"] == [
        {
            "permission": "order.order.view",
            "permission_name": "查看订单",
            "scope": "GLOBAL",
            "scope_name": "全局",
            "expires_at": None,
            "source": MEMBERSHIP_SOURCE_DEPARTMENT,
        },
    ]
    assert row["groups"] == [{"key": "sales", "kind": "role", "name": "销售"}]
    grants = row["grants"]
    assert isinstance(grants, list)
    assert {item["source_type"] for item in grants} == {"group", "direct"}

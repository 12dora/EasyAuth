from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Final

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.admin_console.grant_row_payloads import (
    access_grant_row_queryset,
    serialize_access_grant_row,
    serialize_access_grant_rows,
)
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import (
    GRANT_STATUS_REVOKED,
    MEMBERSHIP_SOURCE_DEPARTMENT,
    MEMBERSHIP_SOURCE_USER,
    AccessGrant,
    AccessGrantGroup,
    AccessGrantPermission,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

pytestmark = pytest.mark.django_db

_LIST_SERIALIZE_QUERIES: Final = 0
_LIST_ROW_COUNT: Final = 20


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


def test_serialize_access_grant_row_keeps_expired_historical_lifecycle() -> None:
    user = UserMirror.objects.create(authentik_user_id="grant-row-historical-user")
    app = App.objects.create(app_key="grant-row-historical-app", name="CRM")
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
    expired_at = timezone.now() - timedelta(days=2)
    grant = AccessGrant.objects.create(
        user=user,
        app=app,
        status=GRANT_STATUS_REVOKED,
        is_current=False,
    )
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=expired_at,
        source=MEMBERSHIP_SOURCE_USER,
    )

    row = serialize_access_grant_row(grant)

    assert row["is_current"] is False
    assert row["grant_type"] == "timed"
    assert row["grant_expires_at"] == expired_at.isoformat()
    assert row["groups"] == [{"key": "sales", "kind": "role", "name": "销售"}]


def test_serialize_access_grant_rows_query_count_does_not_grow_with_row_count(
    django_assert_num_queries: Callable[[int], AbstractContextManager[object]],
) -> None:
    grants = _grants_for_list_query_count(_LIST_ROW_COUNT)
    one = list(access_grant_row_queryset().filter(pk=grants[0].pk))
    twenty = list(access_grant_row_queryset().filter(pk__in=[grant.pk for grant in grants]))

    with django_assert_num_queries(_LIST_SERIALIZE_QUERIES):
        rows_one = serialize_access_grant_rows(one)
    with django_assert_num_queries(_LIST_SERIALIZE_QUERIES):
        rows_twenty = serialize_access_grant_rows(twenty)

    assert len(rows_one) == 1
    assert len(rows_twenty) == _LIST_ROW_COUNT
    assert rows_one[0]["grants"]
    assert rows_twenty[-1]["grants"]


def _grants_for_list_query_count(count: int) -> list[AccessGrant]:
    app = App.objects.create(app_key="grant-row-query-app", name="CRM")
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
    grants: list[AccessGrant] = []
    for index in range(count):
        user = UserMirror.objects.create(authentik_user_id=f"grant-row-query-user-{index}")
        grant = AccessGrant.objects.create(user=user, app=app)
        _ = AccessGrantGroup.objects.create(
            grant=grant,
            authorization_group=group,
            source=MEMBERSHIP_SOURCE_USER,
        )
        _ = AccessGrantPermission.objects.create(
            grant=grant,
            permission=permission,
            scope_key="GLOBAL",
            source=MEMBERSHIP_SOURCE_USER,
        )
        grants.append(grant)
    return grants

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    Permission,
)
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.grants.query import ExpandedGrant, GroupSnapshot
from easyauth.portal.api_data import current_grant_items_for_user
from easyauth.portal.permission_aggregation import json_expanded_grants, json_groups

pytestmark = pytest.mark.django_db


def test_current_permission_api_returns_groups_and_expanded_scoped_grants() -> None:
    # Given: 当前授权同时包含授权组和 direct scoped grant。
    user, app, grant = _create_current_grant("portal-expanded-api")
    self_scope = _create_scope(app, "SELF", "本人")
    team_scope = _create_scope(app, "TEAM", "团队")
    read_permission = _create_permission(app, "orders.read", self_scope.key)
    refund_permission = _create_permission(app, "orders.refund.approve", team_scope.key)
    group = AuthorizationGroup.objects.create(
        app=app,
        key="sales-reader",
        kind="role",
        name="销售只读",
    )
    _ = AuthorizationGroupGrant.objects.create(
        authorization_group=group,
        permission=read_permission,
        scope_key=self_scope.key,
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=refund_permission,
        scope_key=team_scope.key,
    )

    # When: 当前权限 API 聚合授权事实。
    item = current_grant_items_for_user(user)[0]

    # Then: 响应包含授权组快照、expanded grants 和版本信息。
    assert item["groups"] == [{"key": "sales-reader", "kind": "role", "name": "销售只读"}]
    assert item["grants"] == [
        {
            "permission": "orders.read",
            "scope": "SELF",
            "source_type": "group",
            "source_key": "sales-reader",
        },
        {
            "permission": "orders.refund.approve",
            "scope": "TEAM",
            "source_type": "direct",
            "source_key": "",
        },
    ]
    assert item["grant_version"] == grant.version
    assert item["catalog_version"] == app.catalog_version
    assert re.fullmatch(
        rf"{grant.version}\.{app.catalog_version}\.[0-9a-f]{{16}}",
        item["snapshot_version"],
    )


def test_current_permission_api_excludes_inactive_and_deprecated_permissions() -> None:
    # Given: 当前授权包含 active、inactive 和 deprecated direct scoped grants。
    user, app, grant = _create_current_grant("portal-active-only-api")
    scope = _create_scope(app, "GLOBAL", "全局")
    active_permission = _create_permission(app, "invoice.active", scope.key)
    inactive_permission = _create_permission(
        app,
        "invoice.inactive",
        scope.key,
        is_active=False,
    )
    deprecated_permission = _create_permission(
        app,
        "invoice.deprecated",
        scope.key,
        deprecated=True,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=active_permission,
        scope_key=scope.key,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=inactive_permission,
        scope_key=scope.key,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=deprecated_permission,
        scope_key=scope.key,
    )

    # When: 当前权限 API 聚合授权项。
    item = current_grant_items_for_user(user)[0]

    # Then: API 只返回当前有效授权项。
    assert item["grants"] == [
        {
            "permission": active_permission.key,
            "scope": scope.key,
            "source_type": "direct",
            "source_key": "",
        },
    ]


def test_current_permission_api_reports_mixed_membership_lifecycles_without_promotion() -> None:
    # Given: 同一 App 的授权组永久有效, direct permission 单独限时。
    user, app, grant = _create_current_grant("portal-mixed-lifecycle")
    scope = _create_scope(app, "GLOBAL", "全局")
    permission = _create_permission(app, "invoice.read", scope.key)
    group = AuthorizationGroup.objects.create(
        app=app,
        key="reader",
        kind="role",
        name="读者",
    )
    expires_at = timezone.now() + timedelta(days=7)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=None,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=scope.key,
        expires_at=expires_at,
    )

    # When: 门户读取授权生命周期摘要。
    item = current_grant_items_for_user(user)[0]

    # Then: 不把限时项提升为永久, 也不把永久项压成限时。
    assert item["grant_type"] == "mixed"
    assert item["grant_expires_at"] == expires_at.isoformat()


def test_json_helpers_serialize_new_authorization_fact_shapes() -> None:
    # Given: 新授权事实快照包含 groups 和 expanded grants。
    groups = (GroupSnapshot(key="sales-reader", kind="role", name="销售只读", expires_at=None),)
    grants = (
        ExpandedGrant(
            permission="orders.read",
            scope="SELF",
            source_type="group",
            source_key="sales-reader",
            expires_at=None,
        ),
        ExpandedGrant(
            permission="dashboard.view",
            scope="GLOBAL",
            source_type="direct",
            source_key="",
            expires_at=None,
        ),
    )

    # When: 门户 API 序列化授权事实。
    group_payload = json_groups(groups)
    grant_payload = json_expanded_grants(grants)

    # Then: 输出字段与前端表格契约一致。
    assert group_payload == [{"key": "sales-reader", "kind": "role", "name": "销售只读"}]
    assert grant_payload == [
        {
            "permission": "orders.read",
            "scope": "SELF",
            "source_type": "group",
            "source_key": "sales-reader",
        },
        {
            "permission": "dashboard.view",
            "scope": "GLOBAL",
            "source_type": "direct",
            "source_key": "",
        },
    ]


def _create_current_grant(key_suffix: str) -> tuple[UserMirror, App, AccessGrant]:
    user = UserMirror.objects.create(authentik_user_id=f"{key_suffix}-user", name="门户用户")
    app = App.objects.create(app_key=f"{key_suffix}-app", name="门户应用")
    grant = AccessGrant.objects.create(user=user, app=app)
    return user, app, grant


def _create_scope(app: App, key: str, name: str) -> AppScope:
    return AppScope.objects.create(app=app, key=key, name=name)


def _create_permission(
    app: App,
    key: str,
    scope_key: str,
    *,
    is_active: bool = True,
    deprecated: bool = False,
) -> Permission:
    permission = Permission.objects.create(
        app=app,
        key=key,
        name=key,
        is_active=is_active,
        supported_scopes=[scope_key],
    )
    if deprecated:
        permission.deprecated_reason = "废弃"
        permission.deprecated_at = permission.updated_at
        permission.save(update_fields=["deprecated_at", "deprecated_reason"])
    return permission

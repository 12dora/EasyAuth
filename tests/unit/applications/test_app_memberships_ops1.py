from __future__ import annotations

import pytest

from easyauth.applications.models import App, AppMembership
from easyauth.applications.ownership import (
    ConsoleActor,
    apps_visible_to_actor,
    can_manage_app,
    can_operate_credentials,
    can_view_app,
)

pytestmark = pytest.mark.django_db


def test_ops1_owner_can_manage_only_owned_active_app() -> None:
    # Given: 用户只拥有 CRM App 的 active owner membership。
    crm = App.objects.create(app_key="ops1-owner-crm", name="CRM")
    erp = App.objects.create(app_key="ops1-owner-erp", name="ERP")
    actor = ConsoleActor(user_id="owner-001", is_superuser=False)
    _ = AppMembership.objects.create(app=crm, user_id=actor.user_id, role="owner")

    # When: 控制台判断该用户对两个 App 的管理权限。
    crm_allowed = can_manage_app(actor, crm)
    erp_allowed = can_manage_app(actor, erp)

    # Then: owner 只能管理自己负责的 App。
    assert crm_allowed is True
    assert erp_allowed is False


def test_ops1_developer_can_view_but_cannot_manage_or_operate_credentials() -> None:
    # Given: 用户是应用开发者, 不是 owner。
    app = App.objects.create(app_key="ops1-developer-app", name="Developer App")
    actor = ConsoleActor(user_id="developer-001", is_superuser=False)
    _ = AppMembership.objects.create(app=app, user_id=actor.user_id, role="developer")

    # When: 控制台判断查看、管理和凭据操作权限。
    can_view = can_view_app(actor, app)
    can_manage = can_manage_app(actor, app)
    can_operate = can_operate_credentials(actor, app)

    # Then: developer 只能查看接入资料和联调页, 不能修改配置或凭据。
    assert can_view is True
    assert can_manage is False
    assert can_operate is False


def test_ops1_inactive_membership_does_not_grant_console_access() -> None:
    # Given: 用户只有 inactive owner membership。
    app = App.objects.create(app_key="ops1-inactive-owner", name="Inactive Owner")
    actor = ConsoleActor(user_id="former-owner", is_superuser=False)
    _ = AppMembership.objects.create(
        app=app,
        user_id=actor.user_id,
        role="owner",
        is_active=False,
    )

    # When: 控制台判断访问权限。
    can_view = can_view_app(actor, app)
    can_manage = can_manage_app(actor, app)

    # Then: inactive membership 不授予任何控制台访问权限。
    assert can_view is False
    assert can_manage is False


def test_ops1_superuser_can_view_and_manage_all_apps_without_membership() -> None:
    # Given: 系统管理员没有 AppMembership, 但系统中有多个 App。
    crm = App.objects.create(app_key="ops1-super-crm", name="CRM")
    erp = App.objects.create(app_key="ops1-super-erp", name="ERP")
    actor = ConsoleActor(user_id="root", is_superuser=True)

    # When: 控制台列出该用户可见 App 并判断管理权限。
    visible_app_keys = [app.app_key for app in apps_visible_to_actor(actor)]
    can_manage_crm = can_manage_app(actor, crm)
    can_operate_erp = can_operate_credentials(actor, erp)

    # Then: 系统管理员不依赖 membership 即可访问全部 App。
    assert visible_app_keys == ["ops1-super-crm", "ops1-super-erp"]
    assert can_manage_crm is True
    assert can_operate_erp is True

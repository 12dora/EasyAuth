from __future__ import annotations

from typing import Final

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, AuthorizationGroup
from easyauth.grants.inputs import AuthorizationGroupGrantInput
from easyauth.grants.models import DepartmentGrantPolicy, DepartmentGrantPolicyGroup
from easyauth.grants.services import GrantMutationInput, GrantService
from easyauth.webhooks.models import WEBHOOK_EVENT_GRANT_CHANGED, AppWebhookConfig, WebhookDelivery

pytestmark = pytest.mark.django_db

SECRET: Final = "whsec_grant_svc"
EVENTS_URL: Final = "https://app.example.com/api/v1/easyauth/events"
SCOPE_KEY: Final = "GLOBAL"


def _catalog(app_key: str, user_id: str) -> tuple[UserMirror, App, AuthorizationGroup]:
    app = App.objects.create(app_key=app_key, name=app_key)
    _ = AppWebhookConfig.objects.create(app=app, secret=SECRET, events_url=EVENTS_URL, enabled=True)
    _ = AppScope.objects.get_or_create(app=app, key=SCOPE_KEY, defaults={"name": "全局"})
    group = AuthorizationGroup.objects.create(app=app, key="operator", kind="role", name="操作员")
    user = UserMirror.objects.create(authentik_user_id=user_id, status="active")
    return user, app, group


def _grant_changed_count() -> int:
    return WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_GRANT_CHANGED).count()


def test_create_change_revoke_each_emit_exactly_one_grant_changed() -> None:
    user, app, group = _catalog("grant-evt-lifecycle", "grant-evt-user")
    input_data = GrantMutationInput(
        user=user,
        app=app,
        authorization_groups=(AuthorizationGroupGrantInput(group, None),),
        actor_type="admin",
        actor_id="admin-1",
    )

    _ = GrantService.create_grant(input_data)
    assert _grant_changed_count() == 1

    _ = GrantService.change_grant(input_data)
    assert _grant_changed_count() == 2

    _ = GrantService.revoke_grant(
        user=user,
        app=app,
        actor_type="admin",
        actor_id="admin-1",
        reason="test",
    )
    assert _grant_changed_count() == 3
    assert list(
        WebhookDelivery.objects.filter(event_type=WEBHOOK_EVENT_GRANT_CHANGED).values_list(
            "target_url",
            flat=True,
        ),
    ) == [EVENTS_URL, EVENTS_URL, EVENTS_URL]


def test_sync_department_memberships_emits_one_grant_changed_per_committed_change() -> None:
    user, app, group = _catalog("grant-evt-dept", "grant-evt-dept-user")
    policy = DepartmentGrantPolicy.objects.create(
        source_slug="dingtalk",
        corp_id="corp",
        dept_id="1",
        app=app,
        grant_type="permanent",
        reason="部门策略",
        created_by_type="admin",
        created_by_id="admin",
        updated_by_type="admin",
        updated_by_id="admin",
    )
    _ = DepartmentGrantPolicyGroup.objects.create(policy=policy, authorization_group=group)
    groups = (AuthorizationGroupGrantInput(group, None, "department", policy.id),)

    created = GrantService.sync_department_memberships(
        user=user,
        app=app,
        authorization_groups=groups,
        direct_grants=(),
    )
    assert created is not None
    assert _grant_changed_count() == 1

    same = GrantService.sync_department_memberships(
        user=user,
        app=app,
        authorization_groups=groups,
        direct_grants=(),
    )
    assert same is not None
    assert _grant_changed_count() == 1

    removed = GrantService.sync_department_memberships(
        user=user,
        app=app,
        authorization_groups=(),
        direct_grants=(),
    )
    assert removed is not None
    assert _grant_changed_count() == 2

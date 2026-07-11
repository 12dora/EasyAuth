from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import pytest
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AuthorizationGroup
from easyauth.connectors.base import RECONCILE_STATUS_PARTIAL, ReconcileReport
from easyauth.connectors.models import (
    SYNC_TRIGGER_MANUAL,
    ConnectorInstance,
    ConnectorMapping,
    ConnectorSyncRun,
)
from easyauth.connectors.services import (
    _claim_generation,
    _finish_generation,
    build_desired_state,
    mark_reconcile_dirty,
    reconcile_instance,
)
from easyauth.grants.services import (
    AuthorizationGroupGrantInput,
    GrantMutationInput,
    GrantService,
)
from tests.unit.connectors.fakes import FakeConnector

if TYPE_CHECKING:
    from pytest_django.fixtures import SettingsWrapper

pytestmark = pytest.mark.django_db

FAKE_CONNECTOR_PATH = "tests.unit.connectors.fakes.FakeConnector"


@pytest.fixture(autouse=True)
def register_fake_connector(settings: SettingsWrapper) -> None:
    settings.EASYAUTH_CONNECTORS = (FAKE_CONNECTOR_PATH,)
    FakeConnector.reset()


def _app_with_groups(app_key: str) -> tuple[App, AuthorizationGroup, AuthorizationGroup]:
    app = App.objects.create(app_key=app_key, name=app_key)
    mapped = AuthorizationGroup.objects.create(app=app, key="vpn-users", kind="bundle", name="VPN")
    unmapped = AuthorizationGroup.objects.create(app=app, key="vpn-dev", kind="bundle", name="Dev")
    return app, mapped, unmapped


def _grant(user: UserMirror, app: App, groups: tuple[AuthorizationGroup, ...]) -> None:
    _ = GrantService.create_grant(
        GrantMutationInput(
            user=user,
            app=app,
            authorization_groups=tuple(
                AuthorizationGroupGrantInput(authorization_group=group, expires_at=None)
                for group in groups
            ),
            actor_type="user",
            actor_id="tester",
        ),
    )


def test_build_desired_state_projects_only_mapped_groups() -> None:
    # Given: 两个授权组, 只有 vpn-users 建立了映射(auto_create)。
    app, mapped, unmapped = _app_with_groups("conn-desired")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    _ = ConnectorMapping.objects.create(
        instance=instance,
        authorization_group=mapped,
        external_ref="netbird-vpn-users",
        auto_create=True,
    )
    granted = UserMirror.objects.create(
        authentik_user_id="conn-desired-u1",
        name="Granted",
        email="granted@example.com",
    )
    unmapped_only = UserMirror.objects.create(authentik_user_id="conn-desired-u2")
    revoked = UserMirror.objects.create(authentik_user_id="conn-desired-u3")
    _grant(granted, app, (mapped, unmapped))
    _grant(unmapped_only, app, (unmapped,))
    _grant(revoked, app, (mapped,))
    _ = GrantService.revoke_grant(user=revoked, app=app, actor_type="user", actor_id="tester")

    # When
    desired = build_desired_state(instance)

    # Then: 只有映射组投影进 desired; 撤销/仅散装组的用户不出现。
    assert dict(desired.user_groups) == {"conn-desired-u1": frozenset({"netbird-vpn-users"})}
    assert desired.profiles["conn-desired-u1"].email == "granted@example.com"
    assert desired.managed_group_refs == frozenset({"netbird-vpn-users"})
    # external_ref 为不可变组 ID, auto_create 不再进入 desired(避免假成功)。
    assert desired.auto_create_group_refs == frozenset()


def test_build_desired_state_excludes_inactive_group_and_expired_membership() -> None:
    # Given: 停用授权组 + 已过期成员不得进入 VPN desired。
    from easyauth.grants.models import AccessGrantGroup

    app, mapped, _unmapped = _app_with_groups("conn-effective")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    _ = ConnectorMapping.objects.create(
        instance=instance,
        authorization_group=mapped,
        external_ref="netbird-vpn-users",
        auto_create=True,
    )
    active_user = UserMirror.objects.create(authentik_user_id="conn-eff-active")
    expired_user = UserMirror.objects.create(authentik_user_id="conn-eff-expired")
    inactive_group_user = UserMirror.objects.create(authentik_user_id="conn-eff-inactive")
    _grant(active_user, app, (mapped,))
    _grant(expired_user, app, (mapped,))
    expired_membership = AccessGrantGroup.objects.get(
        grant__user=expired_user,
        authorization_group=mapped,
    )
    expired_membership.expires_at = timezone.now() - timedelta(hours=1)
    expired_membership.save(update_fields=["expires_at"])

    inactive_group = AuthorizationGroup.objects.create(
        app=app,
        key="vpn-off",
        kind="bundle",
        name="Off",
        is_active=False,
    )
    _ = ConnectorMapping.objects.create(
        instance=instance,
        authorization_group=inactive_group,
        external_ref="netbird-vpn-off",
    )
    _grant(inactive_group_user, app, (inactive_group,))

    desired = build_desired_state(instance)

    assert dict(desired.user_groups) == {"conn-eff-active": frozenset({"netbird-vpn-users"})}
    assert "conn-eff-expired" not in desired.user_groups
    assert "conn-eff-inactive" not in desired.user_groups
    assert desired.auto_create_group_refs == frozenset()


def test_reconcile_records_run_and_passes_desired_state() -> None:
    # Given
    app, mapped, _unmapped = _app_with_groups("conn-run")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    _ = ConnectorMapping.objects.create(
        instance=instance,
        authorization_group=mapped,
        external_ref="ext-vpn",
    )
    user = UserMirror.objects.create(authentik_user_id="conn-run-u1")
    _grant(user, app, (mapped,))
    FakeConnector.next_report = ReconcileReport(stats={"groups_added": 1})

    # When
    run = reconcile_instance(instance.id, trigger=SYNC_TRIGGER_MANUAL)

    # Then: 运行审计与实例健康字段落库, desired 由框架构建后传入连接器。
    assert run is not None
    assert run.status == "success"
    assert run.trigger == SYNC_TRIGGER_MANUAL
    assert run.stats == {"groups_added": 1}
    desired = FakeConnector.last_desired
    assert desired is not None
    assert dict(desired.user_groups) == {"conn-run-u1": frozenset({"ext-vpn"})}
    instance.refresh_from_db()
    assert instance.last_status == "success"
    assert instance.last_error == ""
    assert instance.consecutive_failures == 0
    assert instance.last_reconcile_at is not None


def test_reconcile_failure_increments_consecutive_failures() -> None:
    # Given
    app, _mapped, _unmapped = _app_with_groups("conn-fail")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    FakeConnector.next_error_message = "外部 API 不可达"

    # When: 连续多轮失败。
    failure_rounds = 2
    first = reconcile_instance(instance.id, trigger=SYNC_TRIGGER_MANUAL)
    for _ in range(failure_rounds - 1):
        _ = reconcile_instance(instance.id, trigger=SYNC_TRIGGER_MANUAL)

    # Then
    assert first is not None
    assert first.status == "failed"
    assert first.error == "外部 API 不可达"
    instance.refresh_from_db()
    assert instance.consecutive_failures == failure_rounds
    assert instance.last_status == "failed"

    # 恢复成功后计数清零。
    FakeConnector.next_error_message = ""
    _ = reconcile_instance(instance.id, trigger=SYNC_TRIGGER_MANUAL)
    instance.refresh_from_db()
    assert instance.consecutive_failures == 0


def test_reconcile_partial_does_not_count_as_failure() -> None:
    # Given: partial 表示护栏截断但仍在推进收敛。
    app, _mapped, _unmapped = _app_with_groups("conn-partial")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    FakeConnector.next_report = ReconcileReport(
        status=RECONCILE_STATUS_PARTIAL,
        error="API 上限",
    )

    # When
    run = reconcile_instance(instance.id, trigger=SYNC_TRIGGER_MANUAL)

    # Then
    assert run is not None
    assert run.status == RECONCILE_STATUS_PARTIAL
    instance.refresh_from_db()
    assert instance.consecutive_failures == 0
    assert instance.last_status == RECONCILE_STATUS_PARTIAL


def test_reconcile_skips_disabled_instance_and_unknown_connector() -> None:
    # Given
    app, _mapped, _unmapped = _app_with_groups("conn-skip")
    disabled = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=False)
    unknown = ConnectorInstance.objects.create(app=app, connector_key="ghost", enabled=True)

    # When / Then: 未启用直接跳过, 不落运行记录。
    assert reconcile_instance(disabled.id, trigger=SYNC_TRIGGER_MANUAL) is None
    assert ConnectorSyncRun.objects.filter(instance=disabled).count() == 0

    # 未注册类型记失败运行(可在控制台看见), 不抛异常。
    run = reconcile_instance(unknown.id, trigger=SYNC_TRIGGER_MANUAL)
    assert run is not None
    assert run.status == "failed"
    assert "未在 EASYAUTH_CONNECTORS 注册" in run.error


def test_reconcile_keeps_dirty_when_token_lease_is_held() -> None:
    # Given: 另一 worker 持有带 owner token 的数据库租约。
    app, _mapped, _unmapped = _app_with_groups("conn-lock")
    instance = ConnectorInstance.objects.create(
        app=app,
        connector_key="fake",
        enabled=True,
        reconcile_lease_token=UUID("54e3c48d-20d4-4996-bc71-8d32123f8944"),
        reconcile_lease_expires_at=timezone.now() + timedelta(minutes=1),
    )

    # When / Then: 请求不丢失, generation/dirty 持久保留。
    assert reconcile_instance(instance.id, trigger=SYNC_TRIGGER_MANUAL) is None
    assert FakeConnector.last_desired is None
    instance.refresh_from_db()
    assert instance.reconcile_generation == 1
    assert instance.reconcile_dirty is True


def test_compare_release_does_not_delete_new_owner_lease() -> None:
    app, _mapped, _unmapped = _app_with_groups("conn-owner-token")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    assert mark_reconcile_dirty(instance.id, trigger=SYNC_TRIGGER_MANUAL)
    old_claim = _claim_generation(instance.id)
    assert old_claim is not None
    new_token = UUID("91be004d-e1f4-4781-a08e-f6e3006685ee")
    _ = ConnectorInstance.objects.filter(id=instance.id).update(
        reconcile_lease_token=new_token,
        reconcile_lease_expires_at=timezone.now() + timedelta(minutes=1),
    )

    released = _finish_generation(old_claim, report=ReconcileReport())

    assert released is False
    instance.refresh_from_db()
    assert instance.reconcile_lease_token == new_token
    assert instance.reconciled_generation == 0


def test_non_active_user_is_never_projected_for_unblock() -> None:
    app, mapped, _unmapped = _app_with_groups("conn-departed")
    instance = ConnectorInstance.objects.create(app=app, connector_key="fake", enabled=True)
    _ = ConnectorMapping.objects.create(
        instance=instance,
        authorization_group=mapped,
        external_ref="immutable-group-id",
    )
    user = UserMirror.objects.create(authentik_user_id="conn-departed-u1", status="departed")
    _grant(user, app, (mapped,))

    desired = build_desired_state(instance)

    assert desired.user_groups == {}
    assert desired.managed_group_refs == frozenset({"immutable-group-id"})


def test_duplicate_external_account_across_apps_fails_second_reconcile() -> None:
    first_app, _mapped, _unmapped = _app_with_groups("conn-account-a")
    second_app, _mapped2, _unmapped2 = _app_with_groups("conn-account-b")
    first = ConnectorInstance.objects.create(app=first_app, connector_key="fake", enabled=True)
    second = ConnectorInstance.objects.create(app=second_app, connector_key="fake", enabled=True)
    FakeConnector.external_account = "immutable-account-id"

    first_run = reconcile_instance(first.id, trigger=SYNC_TRIGGER_MANUAL)
    second_run = reconcile_instance(second.id, trigger=SYNC_TRIGGER_MANUAL)

    assert first_run is not None
    assert first_run.status == "success"
    assert second_run is not None
    assert second_run.status == "failed"
    assert "已绑定" in second_run.error

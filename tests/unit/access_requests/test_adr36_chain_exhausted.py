"""ADR-002 §36: 主管链耗尽提交进 superuser_pool。"""

from __future__ import annotations

import pytest

from easyauth.access_requests.models import AccessRequest
from easyauth.access_requests.services import AccessRequestService
from easyauth.access_requests.submission_types import (
    AccessRequestSubmission,
    AccessRequestSubmissionError,
    ScopedAccessRequestGrant,
)
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import App, AppScope, Permission
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db


def test_no_active_manager_empty_approver_succeeds_superuser_pool() -> None:
    """目录上下文缺失时 routing_reason=no_active_manager。"""
    user = UserMirror.objects.create(
        authentik_user_id="adr36-user",
        name="u",
        status=USER_STATUS_ACTIVE,
        manager_userid="",
    )
    app = App.objects.create(app_key="adr36-app", name="a")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下属")
    permission = Permission.objects.create(
        app=app,
        key="customer.view",
        name="view",
        supported_scopes=["MANAGED_USERS"],
    )
    result = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            grant_type="permanent",
            grant_expires_at=None,
            reason="查看下属客户",
            actor_type="user",
            actor_id=user.authentik_user_id,
            idempotency_key="adr36-empty",
            approver_user_ids=(),
            direct_grants=(
                ScopedAccessRequestGrant(permission=permission, scope_key="MANAGED_USERS"),
            ),
        ),
    )
    assert result.approval_routing_state == "superuser_pool"
    # 无钉钉绑定 / 无目录上下文 → no_active_manager(非伪造的 chain_exhausted)
    assert result.routing_reason == "no_active_manager"
    assert AccessRequest.objects.filter(pk=result.pk).exists()
    assert AuditLog.objects.filter(
        event_type="handover_assignee_resolution_degraded",
    ).count() == 1


def test_missing_manager_chain_does_not_fallback_to_legacy_manager_field() -> None:
    """目录上下文缺失时, 旧 manager_userid 即使指向 active 用户也必须进池。"""
    legacy_manager = UserMirror.objects.create(
        authentik_user_id="adr36-legacy-manager",
        status=USER_STATUS_ACTIVE,
    )
    user = UserMirror.objects.create(
        authentik_user_id="adr36-no-chain",
        status=USER_STATUS_ACTIVE,
        manager_userid=legacy_manager.authentik_user_id,
    )
    app = App.objects.create(app_key="adr36-no-chain-app", name="无主管链应用")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下属")
    permission = Permission.objects.create(
        app=app,
        key="customer.no-chain",
        name="查看",
        supported_scopes=["MANAGED_USERS"],
    )

    result = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            grant_type="permanent",
            grant_expires_at=None,
            reason="验证主管链缺失路由",
            actor_type="user",
            actor_id=user.authentik_user_id,
            idempotency_key="adr36-no-chain",
            approver_user_ids=(),
            direct_grants=(
                ScopedAccessRequestGrant(permission=permission, scope_key="MANAGED_USERS"),
            ),
        ),
    )

    assert result.approval_routing_state == "superuser_pool"
    assert result.routing_reason == "no_active_manager"


def test_chain_exhausted_when_manager_chain_walked_to_end() -> None:
    """链被 walk 到尽头(全部 departed) → routing_reason=chain_exhausted。"""
    departed_mgr = UserMirror.objects.create(
        authentik_user_id="adr36-dep-mgr",
        name="dm",
        status=USER_STATUS_DEPARTED,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid="dm1",
    )
    user = UserMirror.objects.create(
        authentik_user_id="adr36-walked",
        name="w",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid="w1",
        manager_userid="dm1",
    )
    _ = DingTalkUserOrgContext.objects.create(
        source_slug="s",
        corp_id="c",
        user_id="w1",
        manager_chain=[{"user_id": "dm1"}],
        stale=False,
    )
    app = App.objects.create(app_key="adr36-walked-app", name="a")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下属")
    permission = Permission.objects.create(
        app=app,
        key="customer.view.walked",
        name="view",
        supported_scopes=["MANAGED_USERS"],
    )
    result = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            grant_type="permanent",
            grant_expires_at=None,
            reason="查看下属客户",
            actor_type="user",
            actor_id=user.authentik_user_id,
            idempotency_key="adr36-walked",
            approver_user_ids=(),
            direct_grants=(
                ScopedAccessRequestGrant(permission=permission, scope_key="MANAGED_USERS"),
            ),
        ),
    )
    assert result.approval_routing_state == "superuser_pool"
    assert result.routing_reason == "chain_exhausted"
    assert departed_mgr.status == USER_STATUS_DEPARTED


def test_chain_exhausted_non_manager_approver_still_rejected() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="adr36-user2",
        name="u2",
        status=USER_STATUS_ACTIVE,
        manager_userid="",
    )
    other = UserMirror.objects.create(
        authentik_user_id="adr36-other",
        name="o",
        status=USER_STATUS_ACTIVE,
    )
    app = App.objects.create(app_key="adr36-app2", name="a2")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下属")
    permission = Permission.objects.create(
        app=app,
        key="customer.view2",
        name="view",
        supported_scopes=["MANAGED_USERS"],
    )
    with pytest.raises(AccessRequestSubmissionError) as exc:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                grant_type="permanent",
                grant_expires_at=None,
                reason="查看下属客户",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="adr36-bad",
                approver_user_ids=(other.authentik_user_id,),
                direct_grants=(
                    ScopedAccessRequestGrant(
                        permission=permission,
                        scope_key="MANAGED_USERS",
                    ),
                ),
            ),
        )
    assert "direct manager approver" in str(exc.value.messages[0])


def test_active_manager_only_first_accepted() -> None:
    mgr = UserMirror.objects.create(
        authentik_user_id="adr36-mgr",
        name="m",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid="m1",
    )
    other = UserMirror.objects.create(
        authentik_user_id="adr36-other2",
        name="o2",
        status=USER_STATUS_ACTIVE,
    )
    user = UserMirror.objects.create(
        authentik_user_id="adr36-user3",
        name="u3",
        status=USER_STATUS_ACTIVE,
        dingtalk_source_slug="s",
        dingtalk_corp_id="c",
        dingtalk_userid="u3",
        manager_userid="m1",
    )
    _ = DingTalkUserOrgContext.objects.create(
        source_slug="s",
        corp_id="c",
        user_id="u3",
        manager_chain=[{"user_id": "m1"}],
        stale=False,
    )
    app = App.objects.create(app_key="adr36-app3", name="a3")
    _ = AppScope.objects.create(app=app, key="MANAGED_USERS", name="下属")
    permission = Permission.objects.create(
        app=app,
        key="customer.view3",
        name="view",
        supported_scopes=["MANAGED_USERS"],
    )
    ok = AccessRequestService.submit_access_request(
        AccessRequestSubmission(
            user=user,
            app=app,
            grant_type="permanent",
            grant_expires_at=None,
            reason="查看下属客户",
            actor_type="user",
            actor_id=user.authentik_user_id,
            idempotency_key="adr36-ok",
            approver_user_ids=(mgr.authentik_user_id,),
            direct_grants=(
                ScopedAccessRequestGrant(permission=permission, scope_key="MANAGED_USERS"),
            ),
        ),
    )
    assert ok.approval_routing_state == "normal"

    with pytest.raises(AccessRequestSubmissionError):
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                grant_type="permanent",
                grant_expires_at=None,
                reason="查看下属客户",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="adr36-wrong",
                approver_user_ids=(other.authentik_user_id,),
                direct_grants=(
                    ScopedAccessRequestGrant(
                        permission=permission,
                        scope_key="MANAGED_USERS",
                    ),
                ),
            ),
        )


def test_non_managed_users_still_requires_approver() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="adr36-plain",
        name="p",
        status=USER_STATUS_ACTIVE,
    )
    app = App.objects.create(app_key="adr36-plain-app", name="p")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="g")
    permission = Permission.objects.create(
        app=app,
        key="plain.view",
        name="view",
        supported_scopes=["GLOBAL"],
    )
    with pytest.raises(AccessRequestSubmissionError) as exc:
        _ = AccessRequestService.submit_access_request(
            AccessRequestSubmission(
                user=user,
                app=app,
                grant_type="permanent",
                grant_expires_at=None,
                reason="普通权限申请",
                actor_type="user",
                actor_id=user.authentik_user_id,
                idempotency_key="adr36-plain",
                approver_user_ids=(),
                direct_grants=(
                    ScopedAccessRequestGrant(permission=permission, scope_key="GLOBAL"),
                ),
            ),
        )
    assert "at least one approver" in str(exc.value.messages[0])

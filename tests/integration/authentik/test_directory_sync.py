from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
from threading import Event
from typing import TYPE_CHECKING, cast

import pytest
from django.utils import timezone

from easyauth.accounts.models import (
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import App, AppScope, AuthorizationGroup, Permission
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission
from easyauth.integrations.authentik.directory_client import (
    DIRECTORY_NOT_FOUND_MESSAGE,
    AuthentikDirectoryNotFoundError,
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.directory_sync import (
    UnsupportedDirectoryStatusError,
    sync_authentik_dingtalk_directory,
)
from easyauth.lifecycle.models import HandoverAppAction

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

_EXPECTED_TWO_USERS = 2
_FINAL_STATUS_CALL = 2
_NEWER_GENERATION = 2
_CONCURRENT_WAIT_TIMEOUT_MESSAGE = "并发测试等待新 generation 提交超时。"


@dataclass(slots=True)
class _DirectoryClientStub:
    departments: list[dict[str, object]] = field(default_factory=list)
    users: list[dict[str, object]] = field(default_factory=list)
    org_contexts: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)
    # 上游报告的每 corp 用户总数; 缺省时按实际返回用户数上报 (观测==报告)。
    reported_user_count: int | None = None
    generation: int = 1
    status_script: list[dict[str, object]] = field(default_factory=list)
    # 指定这些 (corp_id, user_id) 的 org 拉取抛错, 用于验证单用户失败被隔离。
    org_fetch_errors: set[tuple[str, str]] = field(default_factory=set)

    def get_status(self) -> dict[str, object]:
        if self.status_script:
            return (
                self.status_script.pop(0) if len(self.status_script) > 1 else self.status_script[0]
            )
        reported = (
            self.reported_user_count
            if self.reported_user_count is not None
            else len(
                self.users,
            )
        )
        return {
            "source_slug": "dingtalk",
            "sync": [
                {
                    "corp_id": "corp-1",
                    "generation": self.generation,
                    "status": "success",
                    "finished_at": "2026-06-12T01:00:00+00:00",
                    "counters": {"users": reported, "departments": len(self.departments)},
                    "error": "",
                }
            ],
        }

    def iter_departments(self) -> list[dict[str, object]]:
        return self.departments

    def iter_users(self) -> list[dict[str, object]]:
        return self.users

    def get_user_org(self, corp_id: str, user_id: str) -> dict[str, object]:
        if (corp_id, user_id) in self.org_fetch_errors:
            raise AuthentikDirectoryNotFoundError(DIRECTORY_NOT_FOUND_MESSAGE)
        return self.org_contexts[(corp_id, user_id)]


@dataclass(slots=True)
class _BlockingFinalStatusClient:
    delegate: _DirectoryClientStub
    final_status_started: Event
    allow_final_status: Event
    status_call_count: int = 0

    def get_status(self) -> dict[str, object]:
        self.status_call_count += 1
        if self.status_call_count == _FINAL_STATUS_CALL:
            self.final_status_started.set()
            if not self.allow_final_status.wait(timeout=5):
                raise AssertionError(_CONCURRENT_WAIT_TIMEOUT_MESSAGE)
        return self.delegate.get_status()

    def iter_departments(self) -> list[dict[str, object]]:
        return self.delegate.iter_departments()

    def iter_users(self) -> list[dict[str, object]]:
        return self.delegate.iter_users()

    def get_user_org(self, corp_id: str, user_id: str) -> dict[str, object]:
        return self.delegate.get_user_org(corp_id, user_id)


def test_directory_sync_caches_departments_users_and_org_context() -> None:
    _ = UserMirror.objects.create(
        authentik_user_id="ak-user-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-1",
    )
    client_stub = _DirectoryClientStub(
        departments=[
            {
                "corp_id": "corp-1",
                "dept_id": "dept-1",
                "parent_id": "",
                "name": "销售部",
                "order": 10,
            }
        ],
        users=[
            {
                "corp_id": "corp-1",
                "user_id": "user-1",
                "union_id": "union-1",
                "name": "张三",
                "avatar": "https://static-legacy.dingtalk.com/media/user-1.jpg",
                "title": "销售经理",
                "department_ids": ["dept-1"],
                "manager_userid": "manager-1",
                "status": "active",
            }
        ],
        org_contexts={
            ("corp-1", "user-1"): {
                "corp_id": "corp-1",
                "user_id": "user-1",
                "departments": [{"dept_id": "dept-1", "name": "销售部"}],
                "manager": {"user_id": "manager-1", "name": "主管"},
                "manager_chain": [{"user_id": "manager-1", "name": "主管"}],
                "stale": False,
            }
        },
    )

    result = sync_authentik_dingtalk_directory(client_stub)

    assert result.department_count == 1
    assert result.user_count == 1
    assert result.org_context_count == 1
    assert DingTalkDepartmentMirror.objects.get(corp_id="corp-1", dept_id="dept-1").name == "销售部"
    user_mirror = DingTalkUserMirror.objects.get(corp_id="corp-1", user_id="user-1")
    assert user_mirror.manager_userid == "manager-1"
    assert user_mirror.avatar == "https://static-legacy.dingtalk.com/media/user-1.jpg"
    assert user_mirror.title == "销售经理"
    org_context = DingTalkUserOrgContext.objects.get(corp_id="corp-1", user_id="user-1")
    manager_chain = cast("list[dict[str, JsonValue]]", org_context.manager_chain)
    assert manager_chain[0]["user_id"] == "manager-1"
    assert DingTalkDirectorySyncState.objects.get(corp_id="corp-1").status == "success"
    user = UserMirror.objects.get(authentik_user_id="ak-user-1")
    assert user.department == "销售部"
    assert user.manager_userid == "manager-1"


def _stub_with_users(users: list[dict[str, object]]) -> _DirectoryClientStub:
    return _DirectoryClientStub(
        users=users,
        org_contexts={
            (cast("str", user["corp_id"]), cast("str", user["user_id"])): {
                "corp_id": user["corp_id"],
                "user_id": user["user_id"],
                "departments": [],
                "manager": {},
                "manager_chain": [],
                "stale": False,
            }
            for user in users
        },
    )


def test_directory_sync_backfills_empty_user_mirror_avatar_url() -> None:
    # Given: 已绑定钉钉的用户尚未有头像, 目录侧下发了真实头像 URL。
    _ = UserMirror.objects.create(
        authentik_user_id="ak-avatar-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-avatar",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-avatar",
                "name": "头像用户",
                "avatar": "https://static-legacy.dingtalk.com/media/user-avatar.jpg",
                "department_ids": [],
                "manager_userid": "",
                "status": "active",
            },
        ],
    )

    # When: 执行目录同步。
    _ = sync_authentik_dingtalk_directory(client_stub)

    # Then: 空的 avatar_url 被目录头像回填。
    user = UserMirror.objects.get(authentik_user_id="ak-avatar-1")
    assert user.avatar_url == "https://static-legacy.dingtalk.com/media/user-avatar.jpg"


def test_directory_sync_keeps_existing_user_mirror_avatar_url() -> None:
    # Given: 用户已有 OIDC 登录写入的头像, 目录侧下发了不同的头像 URL。
    _ = UserMirror.objects.create(
        authentik_user_id="ak-avatar-2",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-avatar-kept",
        avatar_url="https://oidc.example.test/media/original.jpg",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-avatar-kept",
                "name": "已有头像用户",
                "avatar": "https://static-legacy.dingtalk.com/media/directory.jpg",
                "department_ids": [],
                "manager_userid": "",
                "status": "active",
            },
        ],
    )

    # When: 执行目录同步。
    _ = sync_authentik_dingtalk_directory(client_stub)

    # Then: 目录头像只做空值回填, 不覆盖 OIDC 登录写入的值。
    user = UserMirror.objects.get(authentik_user_id="ak-avatar-2")
    assert user.avatar_url == "https://oidc.example.test/media/original.jpg"


def test_directory_sync_persists_directory_contacts_without_user_mirror() -> None:
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "never-sso-user",
                "name": "未登录员工",
                "email": "never-sso@example.com",
                "mobile": "13800000009",
                "employee_number": "E0009",
                "status": "active",
            },
        ],
    )

    _ = sync_authentik_dingtalk_directory(client_stub)

    mirror = DingTalkUserMirror.objects.get(user_id="never-sso-user")
    assert mirror.email == "never-sso@example.com"
    assert mirror.mobile == "13800000009"
    assert mirror.employee_number == "E0009"
    assert mirror.last_seen_generation == 1
    assert mirror.is_tombstone is False
    assert not UserMirror.objects.filter(dingtalk_userid="never-sso-user").exists()


def test_directory_tombstone_retains_contacts_and_reappearance_clears_it() -> None:
    _ = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        user_id="returning-user",
        name="暂时消失员工",
        email="returning@example.com",
        mobile="13800000008",
        employee_number="E0008",
        status="active",
        last_seen_generation=1,
    )
    missing_snapshot = _stub_with_users([])
    missing_snapshot.generation = 2

    _ = sync_authentik_dingtalk_directory(missing_snapshot)

    tombstone = DingTalkUserMirror.objects.get(user_id="returning-user")
    assert tombstone.status == "departed"
    assert tombstone.is_tombstone is True
    assert tombstone.departed_at is not None
    assert tombstone.email == "returning@example.com"
    assert tombstone.mobile == "13800000008"
    assert tombstone.employee_number == "E0008"
    assert tombstone.last_seen_generation == 1

    returning_snapshot = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "returning-user",
                "name": "重新出现员工",
                "email": "new-returning@example.com",
                "mobile": "13800000007",
                "employee_number": "E0008",
                "status": "active",
            },
        ],
    )
    returning_snapshot.generation = 3

    _ = sync_authentik_dingtalk_directory(returning_snapshot)

    active = DingTalkUserMirror.objects.get(user_id="returning-user")
    assert active.status == "active"
    assert active.is_tombstone is False
    assert active.departed_at is None
    assert active.last_seen_generation == returning_snapshot.generation
    assert active.email == "new-returning@example.com"


def test_directory_sync_marks_deleted_directory_user_departed_and_revokes_grants() -> None:
    # Given: 已绑定钉钉的 active 用户持有 current 授权, 上游目录标记该用户已删除。
    user = UserMirror.objects.create(
        authentik_user_id="ak-departed-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-departed",
        status="active",
    )
    app = App.objects.create(app_key="sync-departed-app", name="Departed App")
    grant = AccessGrant.objects.create(user=user, app=app)
    group = AuthorizationGroup.objects.create(
        app=app,
        key="active-membership",
        kind="role",
        name="有效授权组",
    )
    _ = AccessGrantGroup.objects.create(grant=grant, authorization_group=group)
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-departed",
                "name": "离职用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "deleted",
            },
        ],
    )

    # When: 执行目录同步。
    result = sync_authentik_dingtalk_directory(client_stub)

    # Then: 用户被标记离职, current 授权被撤销并写入审计。
    user.refresh_from_db()
    grant.refresh_from_db()
    assert result.departed_count == 1
    assert result.revoked_count == 1
    assert user.status == "departed"
    assert grant.status == "revoked"
    assert grant.is_current is False
    assert AuditLog.objects.filter(
        event_type="user_departure_detected",
        target_id="ak-departed-1",
    ).exists()
    assert HandoverAppAction.objects.filter(app=app).exists()


def test_directory_sync_normalizes_inactive_user_to_disabled() -> None:
    _ = UserMirror.objects.create(
        authentik_user_id="ak-disabled-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-disabled",
        status="active",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-disabled",
                "name": "停用用户",
                "status": "inactive",
            },
        ],
    )

    _ = sync_authentik_dingtalk_directory(client_stub)

    directory_user = DingTalkUserMirror.objects.get(user_id="user-disabled")
    user = UserMirror.objects.get(authentik_user_id="ak-disabled-1")
    assert directory_user.status == "disabled"
    assert directory_user.is_tombstone is False
    assert directory_user.departed_at is None
    assert user.status == "disabled"


def test_directory_sync_excludes_grant_when_all_memberships_expired() -> None:
    # Given: 父授权仍是 active/current, 但 group 与 direct membership 都已过期。
    user = UserMirror.objects.create(
        authentik_user_id="ak-expired-memberships",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-expired-memberships",
        status="active",
    )
    app = App.objects.create(app_key="sync-expired-memberships-app", name="Expired Memberships")
    scope = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    group = AuthorizationGroup.objects.create(
        app=app,
        key="expired-group",
        kind="role",
        name="已过期授权组",
    )
    permission = Permission.objects.create(
        app=app,
        key="expired.permission",
        name="已过期权限",
        supported_scopes=[scope.key],
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    expired_at = timezone.now() - timedelta(seconds=1)
    _ = AccessGrantGroup.objects.create(
        grant=grant,
        authorization_group=group,
        expires_at=expired_at,
    )
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key=scope.key,
        expires_at=expired_at,
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-expired-memberships",
                "status": "deleted",
            },
        ],
    )

    _ = sync_authentik_dingtalk_directory(client_stub)

    grant.refresh_from_db()
    assert grant.status == "revoked"
    assert not HandoverAppAction.objects.filter(app=app).exists()


def test_directory_sync_departs_bound_user_missing_from_directory() -> None:
    # Given: 用户绑定 corp-1, 但上游目录响应中已完全没有该用户。
    user = UserMirror.objects.create(
        authentik_user_id="ak-missing-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-missing",
        status="active",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-other",
                "name": "在职用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "active",
            },
        ],
    )

    # When: 执行目录同步。
    _ = sync_authentik_dingtalk_directory(client_stub)

    # Then: 目录中消失的绑定用户按离职处理。
    user.refresh_from_db()
    assert user.status == "departed"


def test_directory_sync_applies_authoritative_empty_user_snapshot() -> None:
    # Given: success status 明确声明 generation 与 users=0, 表示合法权威空集。
    user = UserMirror.objects.create(
        authentik_user_id="ak-guard-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-guard",
        status="active",
    )
    app = App.objects.create(app_key="sync-empty-app", name="Empty Snapshot App")
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        user_id="user-guard",
        status="active",
    )
    client_stub = _stub_with_users([])

    # When: 执行目录同步。
    result = sync_authentik_dingtalk_directory(client_stub)

    # Then: 合法空集会把最后一名目录用户转成 tombstone, 并执行离职撤权。
    user.refresh_from_db()
    grant.refresh_from_db()
    assert user.status == "departed"
    assert grant.status == "revoked"
    assert result.status_applied_count == 1
    assert result.tombstoned_user_count == 1
    tombstone = DingTalkUserMirror.objects.get(corp_id="corp-1", user_id="user-guard")
    assert tombstone.status == "departed"
    assert tombstone.is_tombstone is True
    assert tombstone.departed_at is not None


def test_directory_sync_clears_manager_and_prunes_missing_rows() -> None:
    # Given: 镜像里有旧部门/旧用户/旧主管, 上游已经删除部门并清空主管。
    user = UserMirror.objects.create(
        authentik_user_id="ak-clear-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-clear",
        department="旧部门",
        manager_userid="old-manager",
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        dept_id="dept-stale",
        name="被删除部门",
    )
    _ = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        user_id="user-stale",
        name="被删除用户",
    )
    client_stub = _DirectoryClientStub(
        users=[
            {
                "corp_id": "corp-1",
                "user_id": "user-clear",
                "name": "在职用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "active",
            },
        ],
        org_contexts={
            ("corp-1", "user-clear"): {
                "corp_id": "corp-1",
                "user_id": "user-clear",
                "departments": [],
                "manager": {},
                "manager_chain": [],
                "stale": False,
            },
        },
    )

    # When: 执行目录同步。
    result = sync_authentik_dingtalk_directory(client_stub)

    # Then: 主管与部门被清空, 上游不存在的镜像行转为 departed tombstone。
    user.refresh_from_db()
    assert user.manager_userid == ""
    assert user.department == ""
    assert result.pruned_department_count == 1
    assert result.tombstoned_user_count == 1
    assert not DingTalkDepartmentMirror.objects.filter(dept_id="dept-stale").exists()
    tombstone = DingTalkUserMirror.objects.get(user_id="user-stale")
    assert tombstone.status == "departed"
    assert tombstone.is_tombstone is True


def test_directory_sync_rejects_unknown_status_before_any_write() -> None:
    # Given: 一个用户状态无法识别, 另一个用户已删除且持有 current 授权。
    unknown_user = UserMirror.objects.create(
        authentik_user_id="ak-unknown-status",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-unknown",
        status="active",
    )
    departed_user = UserMirror.objects.create(
        authentik_user_id="ak-departed-2",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-departed-2",
        status="active",
    )
    app = App.objects.create(app_key="sync-unknown-app", name="Unknown Status App")
    grant = AccessGrant.objects.create(user=departed_user, app=app)
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-unknown",
                "name": "冻结用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "suspended",
            },
            {
                "corp_id": "corp-1",
                "user_id": "user-departed-2",
                "name": "离职用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "deleted",
            },
        ],
    )

    # When / Then: 任一状态违反契约时整份快照在写入前失败。
    with pytest.raises(UnsupportedDirectoryStatusError):
        _ = sync_authentik_dingtalk_directory(client_stub)

    unknown_user.refresh_from_db()
    departed_user.refresh_from_db()
    grant.refresh_from_db()
    # 未知状态用户既不改状态也不回收。
    assert unknown_user.status == "active"
    # 同一快照中的离职用户也不能在契约失败后产生部分写入。
    assert departed_user.status == "active"
    assert grant.status != "revoked"
    assert not DingTalkUserMirror.objects.exists()


def test_directory_sync_refuses_prune_when_response_truncated() -> None:
    # Given: 上游报告 3 个用户, 但本轮响应只截断返回 1 个, 且仍有绑定用户在职。
    bound_user = UserMirror.objects.create(
        authentik_user_id="ak-truncated-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-truncated",
        status="active",
    )
    app = App.objects.create(app_key="sync-truncated-app", name="Truncated App")
    grant = AccessGrant.objects.create(user=bound_user, app=app)
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-present",
                "name": "在职用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "active",
            },
        ],
    )
    client_stub.reported_user_count = 3

    # When / Then: 完整性护栏发现观测数低于报告总数, 拒绝 prune/回收并触发重试。
    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = sync_authentik_dingtalk_directory(client_stub)

    bound_user.refresh_from_db()
    grant.refresh_from_db()
    # 截断响应不得撤销任何在职用户的授权。
    assert bound_user.status == "active"
    assert grant.status != "revoked"
    assert grant.is_current is True


def test_directory_sync_completeness_guard_counts_distinct_users() -> None:
    # Given: 上游报告 2 个用户, 但响应里是同一个用户的两条重复行(唯一用户其实被截断到 1)。
    bound_user = UserMirror.objects.create(
        authentik_user_id="ak-dup-guard",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-still-bound",
        status="active",
    )
    app = App.objects.create(app_key="sync-dup-app", name="Dup Guard App")
    grant = AccessGrant.objects.create(user=bound_user, app=app)
    duplicated_user = {
        "corp_id": "corp-1",
        "user_id": "user-present",
        "name": "在职用户",
        "department_ids": [],
        "manager_userid": "",
        "status": "active",
    }
    client_stub = _stub_with_users([duplicated_user, dict(duplicated_user)])
    client_stub.reported_user_count = 2

    # When / Then: 去重后观测=1 < 报告=2, 完整性护栏应拒绝而非放行误撤。
    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = sync_authentik_dingtalk_directory(client_stub)

    bound_user.refresh_from_db()
    grant.refresh_from_db()
    assert bound_user.status == "active"
    assert grant.status != "revoked"


def test_directory_sync_isolates_single_user_org_fetch_failure() -> None:
    # Given: 两个用户, 其中一个的 org 上下文持续 404, 另一个正常。
    _ = UserMirror.objects.create(
        authentik_user_id="ak-org-ok",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-org-ok",
        status="active",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-org-ok",
                "name": "正常用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "active",
            },
            {
                "corp_id": "corp-1",
                "user_id": "user-org-broken",
                "name": "org 故障用户",
                "department_ids": [],
                "manager_userid": "",
                "status": "active",
            },
        ],
    )
    client_stub.org_fetch_errors = {("corp-1", "user-org-broken")}

    # When: 执行目录同步。
    result = sync_authentik_dingtalk_directory(client_stub)

    # Then: 单个用户 org 失败被隔离, 同步整体完成并聚合失败计数。
    assert result.user_count == _EXPECTED_TWO_USERS
    assert result.org_context_count == 1
    assert result.org_fetch_failed_count == 1
    assert DingTalkUserOrgContext.objects.filter(user_id="user-org-ok").exists()
    assert not DingTalkUserOrgContext.objects.filter(user_id="user-org-broken").exists()


def test_first_department_population_does_not_flag_change() -> None:
    # Given: 镜像还没有部门信息(首次同步补数据, 不是转岗)。
    _ = UserMirror.objects.create(
        authentik_user_id="ak-first-dept",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-first",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-first",
                "union_id": "union-first",
                "name": "首同步",
                "status": "active",
            }
        ],
    )
    client_stub.org_contexts[("corp-1", "user-first")] = {
        "corp_id": "corp-1",
        "user_id": "user-first",
        "departments": [{"dept_id": "dept-1", "name": "销售部"}],
        "manager": {},
        "manager_chain": [],
        "stale": False,
    }

    # When: 同步。
    _ = sync_authentik_dingtalk_directory(client_stub)

    # Then: 部门被补齐, 但不误报"部门已变更"。
    user = UserMirror.objects.get(authentik_user_id="ak-first-dept")
    assert user.department == "销售部"
    assert user.department_changed_at is None


def test_multi_department_reorder_does_not_flag_change() -> None:
    # Given: 多部门员工, 镜像已存(按 dept_id 稳定排序的)首选部门"销售部"。
    _ = UserMirror.objects.create(
        authentik_user_id="ak-multi-dept",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-multi",
        department="销售部",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-multi",
                "union_id": "union-multi",
                "name": "多部门",
                "status": "active",
            }
        ],
    )
    # 上游把两个部门顺序颠倒返回(市场部排到前面), 但员工并未转岗——部门集合没变。
    client_stub.org_contexts[("corp-1", "user-multi")] = {
        "corp_id": "corp-1",
        "user_id": "user-multi",
        "departments": [
            {"dept_id": "dept-2", "name": "市场部"},
            {"dept_id": "dept-1", "name": "销售部"},
        ],
        "manager": {},
        "manager_chain": [],
        "stale": False,
    }

    # When: 同步。
    _ = sync_authentik_dingtalk_directory(client_stub)

    # Then: 稳定排序后首选部门仍是 dept-1 的"销售部", 不因乱序误报转岗。
    user = UserMirror.objects.get(authentik_user_id="ak-multi-dept")
    assert user.department == "销售部"
    assert user.department_changed_at is None


def test_real_department_change_sets_flag() -> None:
    # Given: 镜像已有旧部门。
    _ = UserMirror.objects.create(
        authentik_user_id="ak-moved-dept",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-moved",
        department="市场部",
    )
    client_stub = _stub_with_users(
        [
            {
                "corp_id": "corp-1",
                "user_id": "user-moved",
                "union_id": "union-moved",
                "name": "调岗人",
                "status": "active",
            }
        ],
    )
    client_stub.org_contexts[("corp-1", "user-moved")] = {
        "corp_id": "corp-1",
        "user_id": "user-moved",
        "departments": [{"dept_id": "dept-2", "name": "销售部"}],
        "manager": {},
        "manager_chain": [],
        "stale": False,
    }

    # When: 同步检出部门变化。
    _ = sync_authentik_dingtalk_directory(client_stub)

    # Then: 置位"部门已变更"提示。
    user = UserMirror.objects.get(authentik_user_id="ak-moved-dept")
    assert user.department == "销售部"
    assert user.department_changed_at is not None


def _authority_status(
    *,
    generation: object = 1,
    users: object = 0,
    departments: object = 0,
    status: object = "success",
) -> dict[str, object]:
    return {
        "source_slug": "dingtalk",
        "sync": [
            {
                "corp_id": "corp-1",
                "generation": generation,
                "status": status,
                "finished_at": "2026-07-10T01:00:00+00:00",
                "counters": {"users": users, "departments": departments},
                "error": "",
            },
        ],
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("generation", True),
        ("generation", -1),
        ("users", True),
        ("users", -1),
        ("departments", None),
        ("status", "running"),
    ],
)
def test_directory_sync_rejects_malformed_authority_before_writes(
    field: str,
    value: object,
) -> None:
    kwargs = {field: value}
    client = _DirectoryClientStub(status_script=[_authority_status(**kwargs)])

    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = sync_authentik_dingtalk_directory(client)

    assert not DingTalkDirectorySyncState.objects.exists()
    assert not DingTalkDepartmentMirror.objects.exists()
    assert not DingTalkUserMirror.objects.exists()


def test_directory_sync_rejects_missing_generation_before_writes() -> None:
    payload = _authority_status()
    sync_entry = cast("dict[str, object]", cast("list[object]", payload["sync"])[0])
    del sync_entry["generation"]
    client = _DirectoryClientStub(status_script=[payload])

    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = sync_authentik_dingtalk_directory(client)

    assert not DingTalkDirectorySyncState.objects.exists()


def test_directory_sync_requires_exact_user_and_department_counts() -> None:
    user: dict[str, object] = {
        "corp_id": "corp-1",
        "user_id": "user-extra",
        "status": "active",
    }
    client = _DirectoryClientStub(
        users=[user],
        org_contexts={},
        status_script=[_authority_status(users=0)],
    )

    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = sync_authentik_dingtalk_directory(client)

    assert not DingTalkDirectorySyncState.objects.exists()
    assert not DingTalkUserMirror.objects.exists()


def test_directory_sync_rejects_generation_change_during_fetch() -> None:
    client = _DirectoryClientStub(
        status_script=[
            _authority_status(generation=1),
            _authority_status(generation=2),
        ],
    )

    with pytest.raises(AuthentikDirectoryUnavailableError):
        _ = sync_authentik_dingtalk_directory(client)

    assert not DingTalkDirectorySyncState.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_older_generation_cannot_reactivate_user() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-generation-fence",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-fenced",
        status="active",
    )
    older = _stub_with_users(
        [{"corp_id": "corp-1", "user_id": "user-fenced", "status": "active"}],
    )
    older.generation = 1
    final_status_started = Event()
    allow_final_status = Event()
    blocked_older = _BlockingFinalStatusClient(
        delegate=older,
        final_status_started=final_status_started,
        allow_final_status=allow_final_status,
    )
    newer = _stub_with_users(
        [{"corp_id": "corp-1", "user_id": "user-fenced", "status": "deleted"}],
    )
    newer.generation = _NEWER_GENERATION

    # 旧任务先抓到 active 列表并停在最终 status 确认; 新任务随后提交 departed generation。
    with ThreadPoolExecutor(max_workers=1) as executor:
        old_future = executor.submit(sync_authentik_dingtalk_directory, blocked_older)
        assert final_status_started.wait(timeout=5)
        _ = sync_authentik_dingtalk_directory(newer)
        allow_final_status.set()
        with pytest.raises(AuthentikDirectoryUnavailableError):
            _ = old_future.result()

    user.refresh_from_db()
    state = DingTalkDirectorySyncState.objects.get(corp_id="corp-1")
    assert user.status == "departed"
    assert state.generation == _NEWER_GENERATION


def test_directory_sync_treats_equal_generation_as_idempotent_noop() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-generation-equal",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-equal",
        status="active",
    )
    initial = _stub_with_users(
        [{"corp_id": "corp-1", "user_id": "user-equal", "status": "active"}],
    )
    initial.generation = 3
    _ = sync_authentik_dingtalk_directory(initial)

    conflicting = _stub_with_users(
        [{"corp_id": "corp-1", "user_id": "user-equal", "status": "deleted"}],
    )
    conflicting.generation = 3
    result = sync_authentik_dingtalk_directory(conflicting)

    user.refresh_from_db()
    assert result.status_applied_count == 0
    assert user.status == "active"

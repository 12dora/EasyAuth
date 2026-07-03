from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from easyauth.accounts.models import (
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
    DingTalkUserOrgContext,
    UserMirror,
)
from easyauth.applications.models import App
from easyauth.audit.models import AuditLog
from easyauth.grants.models import AccessGrant
from easyauth.integrations.authentik.directory_sync import sync_authentik_dingtalk_directory

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db


@dataclass(slots=True)
class _DirectoryClientStub:
    departments: list[dict[str, object]] = field(default_factory=list)
    users: list[dict[str, object]] = field(default_factory=list)
    org_contexts: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)

    def get_status(self) -> dict[str, object]:
        return {
            "source_slug": "dingtalk",
            "sync": [
                {
                    "corp_id": "corp-1",
                    "status": "success",
                    "finished_at": "2026-06-12T01:00:00+00:00",
                    "counters": {"users": 1, "departments": 1},
                    "error": "",
                }
            ],
        }

    def iter_departments(self) -> list[dict[str, object]]:
        return self.departments

    def iter_users(self) -> list[dict[str, object]]:
        return self.users

    def get_user_org(self, corp_id: str, user_id: str) -> dict[str, object]:
        return self.org_contexts[(corp_id, user_id)]


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
    assert (
        DingTalkUserMirror.objects.get(corp_id="corp-1", user_id="user-1").manager_userid
        == "manager-1"
    )
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


def test_directory_sync_does_not_depart_users_when_corp_response_is_empty() -> None:
    # Given: 绑定用户存在, 但上游返回空用户列表(疑似故障)。
    user = UserMirror.objects.create(
        authentik_user_id="ak-guard-1",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="user-guard",
        status="active",
    )
    client_stub = _stub_with_users([])

    # When: 执行目录同步。
    result = sync_authentik_dingtalk_directory(client_stub)

    # Then: 空响应不触发任何离职回收。
    user.refresh_from_db()
    assert user.status == "active"
    assert result.status_applied_count == 0


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

    # Then: 主管与部门被清空, 上游不存在的镜像行被删除。
    user.refresh_from_db()
    assert user.manager_userid == ""
    assert user.department == ""
    assert result.pruned_department_count == 1
    assert result.pruned_user_count == 1
    assert not DingTalkDepartmentMirror.objects.filter(dept_id="dept-stale").exists()
    assert not DingTalkUserMirror.objects.filter(user_id="user-stale").exists()

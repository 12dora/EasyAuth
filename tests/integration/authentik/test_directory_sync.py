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

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import pytest

from easyauth.accounts.models import DingTalkUserMirror
from easyauth.integrations.authentik.directory_client import AuthentikDirectoryUnavailableError
from easyauth.integrations.authentik.directory_payloads import DingTalkDirectoryStatus
from easyauth.integrations.authentik.directory_refresh import (
    REFRESH_TIMEOUT_MESSAGE,
    REFRESH_UPSTREAM_FAILED_MESSAGE,
    RefreshWaitPolicy,
    refresh_dingtalk_directory,
)

if TYPE_CHECKING:
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

pytestmark = pytest.mark.django_db

_BASELINE_FINISHED_AT = "2026-07-06T00:00:00+00:00"
_FRESH_FINISHED_AT = "2026-07-06T00:05:00+00:00"


@dataclass(slots=True)
class _RefreshClientStub:
    """触发前返回基线状态, 触发后按脚本逐次给出同步状态。"""

    status_script: list[dict[str, object]] = field(default_factory=list)
    users: list[dict[str, object]] = field(default_factory=list)
    departments: list[dict[str, object]] = field(default_factory=list)
    org_contexts: dict[tuple[str, str], dict[str, object]] = field(default_factory=dict)
    triggered_corp_ids: list[str] = field(default_factory=list)

    def get_status(self) -> DingTalkDirectoryStatus:
        entry = self.status_script.pop(0) if len(self.status_script) > 1 else self.status_script[0]
        return DingTalkDirectoryStatus(
            source_slug="dingtalk",
            sync=(cast("DirectoryJson", entry),),
        )

    def trigger_sync(self, corp_id: str) -> None:
        self.triggered_corp_ids.append(corp_id)

    def iter_departments(self) -> list[dict[str, object]]:
        return self.departments

    def iter_users(self) -> list[dict[str, object]]:
        return self.users

    def get_user_org(self, corp_id: str, user_id: str) -> dict[str, object]:
        return self.org_contexts[(corp_id, user_id)]


def _status_entry(
    status: str, finished_at: str, *, users: int = 1, error: str = ""
) -> dict[str, object]:
    return {
        "corp_id": "corp-1",
        "status": status,
        "finished_at": finished_at,
        "counters": {"users": users},
        "error": error,
    }


def _instant_policy() -> RefreshWaitPolicy:
    # 不真实 sleep; monotonic 用可控自增序列驱动超时判定。
    clock = iter(float(value) for value in range(10_000))
    return RefreshWaitPolicy(
        timeout_seconds=10.0,
        poll_interval_seconds=0.0,
        sleep=lambda _seconds: None,
        monotonic=lambda: next(clock),
    )


def test_refresh_waits_for_new_sync_then_mirrors_directory() -> None:
    # Given: 基线是上一轮完成状态; 触发后先 running, 再 success。
    client = _RefreshClientStub(
        status_script=[
            _status_entry("success", _BASELINE_FINISHED_AT),
            _status_entry("running", _BASELINE_FINISHED_AT),
            _status_entry("success", _FRESH_FINISHED_AT),
        ],
        users=[
            {
                "corp_id": "corp-1",
                "user_id": "user-1",
                "union_id": "union-1",
                "name": "在职员工",
                "status": "active",
                "department_ids": ["1"],
            },
        ],
        departments=[
            {"corp_id": "corp-1", "dept_id": "1", "parent_id": "", "name": "研发部", "order": 1},
        ],
        org_contexts={
            ("corp-1", "user-1"): {
                "corp_id": "corp-1",
                "user_id": "user-1",
                "departments": [{"dept_id": "1", "name": "研发部"}],
                "manager": {},
                "manager_chain": [],
                "stale": False,
            },
        },
    )

    # When
    result = refresh_dingtalk_directory(client, "corp-1", wait_policy=_instant_policy())

    # Then: 触发了指定企业的同步, 并把最新目录落到镜像表。
    assert client.triggered_corp_ids == ["corp-1"]
    assert result.user_count == 1
    assert DingTalkUserMirror.objects.filter(corp_id="corp-1", user_id="user-1").exists()


def test_refresh_raises_when_upstream_sync_fails() -> None:
    client = _RefreshClientStub(
        status_script=[
            _status_entry("success", _BASELINE_FINISHED_AT),
            _status_entry("error", _FRESH_FINISHED_AT, error="dingtalk api 429"),
        ],
    )

    with pytest.raises(AuthentikDirectoryUnavailableError, match=REFRESH_UPSTREAM_FAILED_MESSAGE):
        _ = refresh_dingtalk_directory(client, "corp-1", wait_policy=_instant_policy())


def test_refresh_raises_on_timeout_while_running() -> None:
    # Given: 上游一直停在 running(finished_at 不前进)。
    client = _RefreshClientStub(
        status_script=[
            _status_entry("success", _BASELINE_FINISHED_AT),
            _status_entry("running", _BASELINE_FINISHED_AT),
        ],
    )
    policy = RefreshWaitPolicy(
        timeout_seconds=5.0,
        poll_interval_seconds=0.0,
        sleep=lambda _seconds: None,
        monotonic=iter([0.0, 1.0, 6.0]).__next__,
    )

    with pytest.raises(AuthentikDirectoryUnavailableError, match=REFRESH_TIMEOUT_MESSAGE):
        _ = refresh_dingtalk_directory(client, "corp-1", wait_policy=policy)

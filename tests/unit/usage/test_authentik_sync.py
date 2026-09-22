from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Self
from urllib.parse import parse_qs, urlparse

import pytest
from django.core.cache import cache

from easyauth.integrations.authentik.directory_client import (
    DIRECTORY_INVALID_FORMAT_MESSAGE,
    DIRECTORY_NOT_FOUND_MESSAGE,
    AuthentikDirectoryNotFoundError,
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.usage_client import (
    AuthentikUsageBucket,
    AuthentikUsageClient,
    AuthentikUsageReport,
    parse_usage_report,
    utc_z,
)
from easyauth.tasks.usage_authentik import sync_authentik_task
from easyauth.usage import authentik_sync as sync_module
from easyauth.usage.authentik_sync import (
    ENFORCEMENT_CACHE_KEY,
    pull,
    push_policy,
    sync,
)
from easyauth.usage.enforcement import EnforcementState
from easyauth.usage.models import UsageBucket, UsageRuntimeState

if TYPE_CHECKING:
    from urllib.request import Request

    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 21, 6, 30, tzinfo=UTC)
SINCE_HOUR = datetime(2026, 9, 21, 3, 0, tzinfo=UTC)
HOUR_START = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body: bytes = body
        self._consumed: bool = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _amount: int = -1) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self._body

    def getheader(self, name: str) -> str | None:
        return str(len(self._body)) if name == "Content-Length" else None


@dataclass
class _FakeUsageClient:
    report: AuthentikUsageReport
    policies: list[DirectoryJson] = field(default_factory=list)
    error: Exception | None = None
    since: datetime | None = None

    def get_usage(self, *, since: datetime) -> AuthentikUsageReport:
        self.since = since
        if self.error is not None:
            raise self.error
        return self.report

    def put_usage_policy(self, policy: DirectoryJson) -> DirectoryJson:
        if self.error is not None:
            raise self.error
        self.policies.append(policy)
        return policy


def _client() -> AuthentikUsageClient:
    return AuthentikUsageClient(
        base_url="https://authentik.test",
        api_token="token-value",
        source_slug="dingtalk",
        timeout_seconds=3,
    )


def _report(*buckets: AuthentikUsageBucket) -> AuthentikUsageReport:
    return AuthentikUsageReport(generated_at=NOW, buckets=buckets)


def _full_bucket(*, count: int = 220, blocked: int = 0) -> AuthentikUsageBucket:
    return AuthentikUsageBucket(
        hour_start=HOUR_START,
        category="ak_directory_full",
        count=count,
        blocked_count=blocked,
    )


def _install_category(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_category(key: str) -> object:
        return type("Cat", (), {"metric": "api", "billed": key != "ak_token"})()

    monkeypatch.setattr(sync_module, "category", fake_category)


def _enforcement_payload(*, api_state: str = "degraded_p2") -> dict[str, object]:
    return {
        "metrics": {
            "api": {
                "metric": "api",
                "state": api_state,
                "reason": "daily_cap",
                "since": NOW.isoformat(),
            },
        },
        "evaluated_at": NOW.isoformat(),
        "stream_paused": False,
        "stream_paused_at": None,
        "stream_paused_period": "",
        "stream_manual_resume_period": "",
    }


def test_utc_z_formats_truncated_utc() -> None:
    assert utc_z(SINCE_HOUR) == "2026-09-21T03:00:00Z"


def test_parse_usage_report_accepts_zulu_hour_and_counts() -> None:
    report = parse_usage_report(
        {
            "generated_at": "2026-09-21T06:12:00Z",
            "buckets": [
                {
                    "hour_start": "2026-09-21T06:11:00Z",
                    "category": "ak_directory_full",
                    "count": 220,
                    "blocked_count": 3,
                },
            ],
        },
    )
    assert report.generated_at == datetime(2026, 9, 21, 6, 12, tzinfo=UTC)
    assert report.buckets == (
        AuthentikUsageBucket(
            hour_start=HOUR_START,
            category="ak_directory_full",
            count=220,
            blocked_count=3,
        ),
    )


def test_parse_usage_report_rejects_bool_count() -> None:
    with pytest.raises(AuthentikDirectoryUnavailableError, match=DIRECTORY_INVALID_FORMAT_MESSAGE):
        _ = parse_usage_report(
            {
                "generated_at": "2026-09-21T06:00:00Z",
                "buckets": [
                    {
                        "hour_start": "2026-09-21T06:00:00Z",
                        "category": "ak_login",
                        "count": True,
                        "blocked_count": 0,
                    },
                ],
            },
        )


def test_get_usage_requests_since_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        _ = timeout
        seen.append(request.full_url)
        return _Response(
            b'{"generated_at":"2026-09-21T06:30:00Z","buckets":[]}',
        )

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)
    report = _client().get_usage(since=SINCE_HOUR)
    parsed = urlparse(seen[0])
    assert parsed.path.endswith("/dingtalk-directory/dingtalk/usage/")
    assert parse_qs(parsed.query)["since"] == ["2026-09-21T03:00:00Z"]
    assert report.buckets == ()


def test_put_usage_policy_sends_put(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []

    def fake_urlopen(request: Request, *, timeout: float) -> _Response:
        _ = timeout
        seen.append((request.get_method(), request.full_url))
        return _Response(b'{"blocked_priorities":["p2"],"expires_at":"2026-09-21T06:10:00Z"}')

    monkeypatch.setattr("easyauth.integrations.authentik.directory_client.urlopen", fake_urlopen)
    echo = _client().put_usage_policy(
        {
            "blocked_priorities": ["p2"],
            "throttle_per_hour": {"p1": None, "p2": 20},
            "block_p0_billed": False,
            "expires_at": "2026-09-21T06:10:00Z",
        },
    )
    assert seen[0][0] == "PUT"
    assert seen[0][1].endswith("/dingtalk-directory/dingtalk/usage-policy/")
    assert echo["blocked_priorities"] == ["p2"]


def test_pull_since_is_three_hours_on_the_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeUsageClient(report=_report())
    _install_category(monkeypatch)
    monkeypatch.setattr(sync_module, "_usage_client", lambda: fake)
    pull(NOW)
    assert fake.since == SINCE_HOUR


def test_pull_upserts_authentik_buckets_and_day_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeUsageClient(
        report=_report(
            _full_bucket(count=220),
            AuthentikUsageBucket(
                hour_start=HOUR_START,
                category="ak_token",
                count=9,
                blocked_count=0,
            ),
        ),
    )
    _install_category(monkeypatch)
    monkeypatch.setattr(sync_module, "_usage_client", lambda: fake)
    pull(NOW)
    billed = UsageBucket.objects.get(source="authentik", category="ak_directory_full")
    token = UsageBucket.objects.get(source="authentik", category="ak_token")
    state = UsageRuntimeState.objects.get(pk=1)
    assert billed.count == 220
    assert billed.billed is True
    assert token.billed is False
    assert token.count == 9
    assert state.authentik_pulled_at == NOW
    assert state.authentik_error == ""
    assert cache.get("usage:day:20260921:api_billed_authentik") == 220


def test_pull_overwrites_count_with_reported_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_category(monkeypatch)
    first = _FakeUsageClient(report=_report(_full_bucket(count=10)))
    monkeypatch.setattr(sync_module, "_usage_client", lambda: first)
    pull(NOW)
    second = _FakeUsageClient(report=_report(_full_bucket(count=4)))
    monkeypatch.setattr(sync_module, "_usage_client", lambda: second)
    pull(NOW)
    assert UsageBucket.objects.get(category="ak_directory_full").count == 4


def test_pull_stores_error_and_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeUsageClient(
        report=_report(),
        error=AuthentikDirectoryUnavailableError(DIRECTORY_INVALID_FORMAT_MESSAGE),
    )
    monkeypatch.setattr(sync_module, "_usage_client", lambda: fake)
    pull(NOW)
    state = UsageRuntimeState.objects.get(pk=1)
    assert state.authentik_pulled_at is None
    assert "用量拉取失败" in state.authentik_error


def test_push_policy_sets_expires_at_plus_ten_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeUsageClient(report=_report())
    monkeypatch.setattr(sync_module, "_usage_client", lambda: fake)
    monkeypatch.setattr(sync_module, "_load_enforcement_state", lambda: object())
    monkeypatch.setattr(
        sync_module,
        "authentik_policy",
        lambda _state: {
            "blocked_priorities": ["p2"],
            "throttle_per_hour": {"p1": None, "p2": 20},
            "block_p0_billed": False,
        },
    )
    push_policy(NOW)
    assert fake.policies == [
        {
            "blocked_priorities": ["p2"],
            "throttle_per_hour": {"p1": None, "p2": 20},
            "block_p0_billed": False,
            "expires_at": utc_z(NOW + timedelta(minutes=10)),
        },
    ]
    state = UsageRuntimeState.objects.get(pk=1)
    assert state.authentik_policy_pushed_at == NOW
    assert state.authentik_error == ""


def test_push_policy_reads_enforcement_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeUsageClient(report=_report())
    seen: list[object] = []
    cache.set(ENFORCEMENT_CACHE_KEY, _enforcement_payload())
    monkeypatch.setattr(sync_module, "_usage_client", lambda: fake)

    def fake_policy(state: object) -> dict[str, object]:
        seen.append(state)
        return {"blocked_priorities": [], "throttle_per_hour": {}}

    monkeypatch.setattr(sync_module, "authentik_policy", fake_policy)
    push_policy(NOW)
    assert len(seen) == 1
    state = seen[0]
    assert isinstance(state, EnforcementState)
    assert state.metrics["api"].state == "degraded_p2"


def test_sync_keeps_pull_error_when_push_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    pull_client = _FakeUsageClient(
        report=_report(),
        error=AuthentikDirectoryUnavailableError("authentik down"),
    )
    push_client = _FakeUsageClient(report=_report())
    clients = iter((pull_client, push_client))
    monkeypatch.setattr(sync_module, "_usage_client", lambda: next(clients))
    monkeypatch.setattr(sync_module, "_load_enforcement_state", lambda: object())
    monkeypatch.setattr(
        sync_module,
        "authentik_policy",
        lambda _state: {"blocked_priorities": [], "throttle_per_hour": {}},
    )
    sync(NOW)
    state = UsageRuntimeState.objects.get(pk=1)
    assert "用量拉取失败" in state.authentik_error
    assert state.authentik_pulled_at is None
    assert state.authentik_policy_pushed_at == NOW
    assert push_client.policies


def test_pull_logs_not_found_once_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def _forbidden(*_args: object, **_kwargs: object) -> None:
        message = "不应使用 logger.exception"
        raise AssertionError(message)

    monkeypatch.setattr(sync_module.logger, "exception", _forbidden)
    fake = _FakeUsageClient(
        report=_report(),
        error=AuthentikDirectoryNotFoundError(DIRECTORY_NOT_FOUND_MESSAGE),
    )
    monkeypatch.setattr(sync_module, "_usage_client", lambda: fake)
    with caplog.at_level(logging.DEBUG, logger=sync_module.logger.name):
        pull(NOW)
        pull(NOW)
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == sync_module.logger.name
    ]
    assert len(warnings) == 1
    assert warnings[0].exc_info is None
    assert "用量拉取失败" in warnings[0].getMessage()
    state = UsageRuntimeState.objects.get(pk=1)
    assert "用量拉取失败" in state.authentik_error


def test_pull_logs_recovery_once(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    failing = _FakeUsageClient(
        report=_report(),
        error=AuthentikDirectoryUnavailableError("down"),
    )
    monkeypatch.setattr(sync_module, "_usage_client", lambda: failing)
    with caplog.at_level(logging.INFO, logger=sync_module.logger.name):
        pull(NOW)
        healthy = _FakeUsageClient(report=_report())
        monkeypatch.setattr(sync_module, "_usage_client", lambda: healthy)
        pull(NOW)
        pull(NOW)
    infos = [
        record
        for record in caplog.records
        if record.levelno == logging.INFO and "已恢复" in record.getMessage()
    ]
    assert len(infos) == 1
    assert UsageRuntimeState.objects.get(pk=1).authentik_error == ""


def test_pull_failure_keeps_unrelated_runtime_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    previous = NOW - timedelta(hours=1)
    _ = UsageRuntimeState.objects.create(
        pk=1,
        enforcement={"keep": True},
        stream_paused=True,
        stream_manual_resume_period="2026-09-21",
        authentik_pulled_at=previous,
        authentik_error="",
    )
    fake = _FakeUsageClient(
        report=_report(),
        error=AuthentikDirectoryUnavailableError("down"),
    )
    monkeypatch.setattr(sync_module, "_usage_client", lambda: fake)
    pull(NOW)
    state = UsageRuntimeState.objects.get(pk=1)
    assert state.enforcement == {"keep": True}
    assert state.stream_paused is True
    assert state.stream_manual_resume_period == "2026-09-21"
    assert state.authentik_pulled_at == previous
    assert "用量拉取失败" in state.authentik_error


def test_sync_authentik_task_calls_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[datetime] = []
    monkeypatch.setattr("easyauth.tasks.usage_authentik.sync", seen.append)
    monkeypatch.setattr("easyauth.tasks.usage_authentik.timezone.now", lambda: NOW)
    sync_authentik_task()
    assert seen == [NOW]

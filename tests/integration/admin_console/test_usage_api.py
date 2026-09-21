from __future__ import annotations

from datetime import datetime, timedelta
from http import HTTPStatus
from json import dumps
from types import SimpleNamespace
from typing import TYPE_CHECKING, Final, cast
from zoneinfo import ZoneInfo

import pytest
from django.test import Client

from easyauth.audit.models import AuditLog
from easyauth.usage.config import UsageConfig
from easyauth.usage.models import UsageAlertEvent, UsageRuntimeState, UsageSettings
from tests.integration.admin_console.auth_helpers import (
    authenticate_console_admin,
    authenticate_console_user,
)

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

SHANGHAI: Final = ZoneInfo("Asia/Shanghai")
FROZEN_NOW: Final = datetime(2026, 9, 21, 12, 0, tzinfo=SHANGHAI)
USAGE_BASE: Final = "/console/api/v1/operations/system-health/usage"
SUMMARY_URL: Final = f"{USAGE_BASE}/summary"
TIMESERIES_URL: Final = f"{USAGE_BASE}/timeseries"
SETTINGS_URL: Final = f"{USAGE_BASE}/settings"
ALERTS_URL: Final = f"{USAGE_BASE}/alerts"
RESUME_URL: Final = f"{USAGE_BASE}/stream/resume"
OLD_HEALTH_URL: Final = "/console/api/v1/operations/dependency-health"

DEFAULT_USAGE_CONFIG: Final[dict[str, object]] = {
    "api": {
        "monthly_quota": 500000,
        "daily_cap": 5000,
        "alert_thresholds_percent": [50, 80, 100],
        "over_limit_policy": "degrade",
        "degrade_escalation_percent": 120,
        "throttle_per_hour": {"p1": 200, "p2": 20},
        "anomaly": {
            "enabled": True,
            "hourly_absolute": None,
            "baseline_multiplier": 5,
            "baseline_min_calls": 200,
        },
    },
    "webhook": {
        "monthly_quota": 50000,
        "daily_cap": None,
        "alert_thresholds_percent": [50, 80, 100],
        "over_limit_policy": "alert_only",
        "anomaly": {
            "enabled": True,
            "hourly_absolute": None,
            "baseline_multiplier": 5,
            "baseline_min_calls": 200,
        },
    },
    "stream": {
        "monthly_quota": None,
        "daily_cap": None,
        "alert_thresholds_percent": [50, 80, 100],
        "over_limit_policy": "alert_only",
        "anomaly": {
            "enabled": True,
            "hourly_absolute": None,
            "baseline_multiplier": 5,
            "baseline_min_calls": 200,
        },
    },
    "alerts": {
        "enabled": True,
        "cooldown_minutes": 60,
        "daily_cap": 30,
        "sender_app_key": "host-ops",
    },
}

TODAY_USED: Final[dict[str, int]] = {"api": 412, "webhook": 10, "stream": 2, "internal": 128}
MONTH_USED: Final[dict[str, int]] = {"api": 9120, "webhook": 20, "stream": 4, "internal": 500}
LAST_HOUR: Final[dict[str, int]] = {"api": 37, "webhook": 1, "stream": 0, "internal": 5}


@pytest.fixture(autouse=True)
def usage_backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    config = UsageConfig.model_validate(DEFAULT_USAGE_CONFIG)
    state: dict[str, object] = {"config": config}
    monkeypatch.setattr("easyauth.admin_console.usage_api.timezone.now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.load_usage_config",
        lambda: state["config"],
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_api.load_usage_config",
        lambda: state["config"],
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.queries.used_today",
        lambda metric: TODAY_USED[str(metric)],
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.queries.used_this_month",
        lambda metric: MONTH_USED[str(metric)],
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.queries.last_60_minutes",
        lambda metric: LAST_HOUR[str(metric)],
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.queries.used_in_range",
        _used_in_range,
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.queries.breakdown",
        _breakdown,
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.queries.timeseries",
        _timeseries,
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.usage_category",
        _category,
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_payloads.alerts.sender_status",
        lambda: (True, None, 3),
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_api.save_usage_config",
        lambda saved, *, updated_by: _save_config(state, saved, updated_by=updated_by),
        raising=False,
    )
    monkeypatch.setattr(
        "easyauth.admin_console.usage_api.resume_stream",
        _resume_stream,
        raising=False,
    )
    return state


def test_usage_summary_shape_projection_and_next_threshold() -> None:
    client = _logged_in_superuser("usage-summary-admin")

    response = client.get(SUMMARY_URL)

    payload = _json_object(response)
    metrics = cast("list[dict[str, JsonValue]]", payload["metrics"])
    api = cast("dict[str, JsonValue]", metrics[0])
    today = cast("dict[str, JsonValue]", api["today"])
    month = cast("dict[str, JsonValue]", api["month"])
    threshold = cast("dict[str, JsonValue]", api["next_threshold"])
    breakdown = cast("dict[str, JsonValue]", payload["api_breakdown_today"])
    alerts = cast("dict[str, JsonValue]", payload["alerts"])
    stream = cast("dict[str, JsonValue]", payload["stream"])
    authentik = cast("dict[str, JsonValue]", payload["authentik"])
    assert response.status_code == HTTPStatus.OK
    assert payload["generated_at"] == "2026-09-21T12:00:00+08:00"
    assert payload["timezone"] == "Asia/Shanghai"
    assert [item["metric"] for item in metrics] == ["api", "webhook", "stream"]
    assert today == {"used": 412, "cap": 5000, "remaining": 4588, "percent": 8.24}
    assert month["used"] == 9120
    assert month["quota"] == 500000
    assert month["remaining"] == 490880
    assert month["percent"] == 1.82
    assert month["period_start"] == "2026-09-01"
    assert month["period_end"] == "2026-09-30"
    assert month["projected"] == round(9120 * 30 / 21)
    assert threshold == {"scope": "day", "percent": 50, "remaining": 2088}
    assert api["blocked_today"] == 3
    assert api["last_hour"] == 37
    assert breakdown == {"total": 600, "billed": 412, "unbilled": 60, "internal": 128}
    assert alerts == {
        "sent_today": 0,
        "suppressed_today": 0,
        "daily_cap": 30,
        "sender_ready": True,
        "sender_problem": None,
        "recipient_count": 3,
    }
    assert stream == {"paused": False, "paused_at": None, "can_resume": False}
    assert authentik["stale"] is True
    webhook_threshold = cast("dict[str, JsonValue]", metrics[1]["next_threshold"])
    assert webhook_threshold == {"scope": "month", "percent": 50, "remaining": 24980}
    assert metrics[2]["next_threshold"] is None
    assert cast("dict[str, JsonValue]", metrics[2]["month"])["projected"] is None


def test_usage_summary_requires_superuser() -> None:
    client = _logged_in_user("usage-summary-user")

    response = client.get(SUMMARY_URL)

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_usage_timeseries_labels_totals_and_default_hour() -> None:
    client = _logged_in_superuser("usage-series-admin")

    response = client.get(TIMESERIES_URL, {"from": "2026-09-21", "to": "2026-09-21"})

    payload = _json_object(response)
    points = cast("list[dict[str, JsonValue]]", payload["points"])
    categories = cast("list[dict[str, JsonValue]]", payload["categories"])
    assert response.status_code == HTTPStatus.OK
    assert payload["from"] == "2026-09-21"
    assert payload["to"] == "2026-09-21"
    assert payload["granularity"] == "hour"
    assert points[0]["start"] == "2026-09-21T00:00:00+08:00"
    assert payload["totals"] == {
        "api_billed": 1,
        "api_unbilled": 0,
        "internal": 5,
        "webhook": 0,
        "stream": 2,
        "blocked": 0,
    }
    assert "label" not in categories[0]
    assert categories[0]["label_zh"] == "工作通知发送"
    assert categories[0]["label_en"] == "Work notice send"


def test_usage_timeseries_default_day_granularity() -> None:
    client = _logged_in_superuser("usage-series-day-admin")

    response = client.get(TIMESERIES_URL, {"from": "2026-09-01", "to": "2026-09-04"})

    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["granularity"] == "day"


def test_usage_timeseries_rejects_bad_ranges() -> None:
    client = _logged_in_superuser("usage-series-bad-admin")

    missing = client.get(TIMESERIES_URL)
    ordered = client.get(TIMESERIES_URL, {"from": "2026-09-22", "to": "2026-09-21"})
    long_range = client.get(TIMESERIES_URL, {"from": "2026-01-01", "to": "2027-02-05"})
    granularity = client.get(
        TIMESERIES_URL,
        {"from": "2026-09-21", "to": "2026-09-21", "granularity": "week"},
    )

    assert missing.status_code == HTTPStatus.BAD_REQUEST
    assert ordered.status_code == HTTPStatus.BAD_REQUEST
    assert long_range.status_code == HTTPStatus.BAD_REQUEST
    assert granularity.status_code == HTTPStatus.BAD_REQUEST
    allowed = client.get(TIMESERIES_URL, {"from": "2026-01-01", "to": "2027-02-04"})
    assert allowed.status_code == HTTPStatus.OK


def test_old_dependency_health_path_is_gone() -> None:
    client = _logged_in_superuser("usage-old-path-admin")

    response = client.get(OLD_HEALTH_URL)

    assert response.status_code == HTTPStatus.NOT_FOUND


def test_usage_settings_get_put_and_audit() -> None:
    client = _logged_in_superuser("usage-settings-admin")
    _ = UsageSettings.objects.create(
        pk=1,
        config=DEFAULT_USAGE_CONFIG,
        version=3,
        updated_by="old-admin",
    )
    body = dict(DEFAULT_USAGE_CONFIG)
    api = dict(cast("dict[str, object]", body["api"]))
    api["daily_cap"] = 4000
    body["api"] = api

    fetched = client.get(SETTINGS_URL)
    updated = client.put(
        SETTINGS_URL,
        data=dumps({"config": body, "version": 3}),
        content_type="application/json",
    )

    fetched_payload = _json_object(fetched)
    updated_payload = _json_object(updated)
    audit = AuditLog.objects.get(event_type="usage_settings_updated")
    changed = cast("list[JsonValue]", audit.metadata["changed_keys"])
    assert fetched.status_code == HTTPStatus.OK
    assert fetched_payload["version"] == 3
    assert updated.status_code == HTTPStatus.OK
    assert updated_payload["version"] == 4
    assert updated_payload["updated_by"] == "usage-settings-admin"
    assert "api.daily_cap" in changed
    assert audit.actor_id == "usage-settings-admin"


def test_usage_settings_version_conflict() -> None:
    client = _logged_in_superuser("usage-settings-conflict-admin")
    _ = UsageSettings.objects.create(
        pk=1,
        config=DEFAULT_USAGE_CONFIG,
        version=3,
        updated_by="old-admin",
    )

    response = client.put(
        SETTINGS_URL,
        data=dumps({"config": DEFAULT_USAGE_CONFIG, "version": 2}),
        content_type="application/json",
    )

    payload = _json_object(response)
    error = cast("dict[str, JsonValue]", payload["error"])
    details = cast("dict[str, JsonValue]", error["details"])
    assert response.status_code == HTTPStatus.CONFLICT
    assert details["reason"] == "version_conflict"
    assert details["current_version"] == 3


def test_usage_settings_validation_shape() -> None:
    client = _logged_in_superuser("usage-settings-invalid-admin")
    invalid = dict(DEFAULT_USAGE_CONFIG)
    invalid["unexpected"] = True

    response = client.put(
        SETTINGS_URL,
        data=dumps({"config": invalid, "version": 0}),
        content_type="application/json",
    )

    payload = _json_object(response)
    error = cast("dict[str, JsonValue]", payload["error"])
    details = cast("dict[str, JsonValue]", error["details"])
    fields = cast("list[JsonValue]", details["fields"])
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert error["code"] == "VALIDATION_ERROR"
    assert "config.unexpected" in fields or "unexpected" in fields


def test_usage_settings_defaults_when_missing() -> None:
    client = _logged_in_superuser("usage-settings-empty-admin")

    response = client.get(SETTINGS_URL)

    payload = _json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert payload["version"] == 0
    assert payload["updated_by"] == ""
    assert payload["updated_at"] == ""


def test_usage_alerts_rejects_bad_limit() -> None:
    client = _logged_in_superuser("usage-alerts-limit-admin")

    response = client.get(ALERTS_URL, {"limit": "0"})

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_usage_settings_requires_superuser() -> None:
    client = _logged_in_user("usage-settings-user")

    response = client.put(
        SETTINGS_URL,
        data=dumps({"config": DEFAULT_USAGE_CONFIG, "version": 0}),
        content_type="application/json",
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


def test_usage_alerts_newest_first() -> None:
    client = _logged_in_superuser("usage-alerts-admin")
    older = _create_alert(
        kind="threshold",
        created_at=FROZEN_NOW - timedelta(hours=2),
        title="旧",
    )
    newer = _create_alert(
        kind="anomaly",
        created_at=FROZEN_NOW,
        title="新",
        period_key="2026-09-21T12",
    )

    response = client.get(ALERTS_URL, {"limit": "1"})

    payload = _json_object(response)
    rows = cast("list[dict[str, JsonValue]]", payload["data"])
    assert response.status_code == HTTPStatus.OK
    assert rows[0]["id"] == newer.id
    assert rows[0]["title"] == "新"
    assert older.id != newer.id


def test_usage_stream_resume_and_audit() -> None:
    client = _logged_in_superuser("usage-resume-admin")
    _create_runtime(stream_paused=True, stream_paused_at=FROZEN_NOW)

    response = client.post(RESUME_URL)

    payload = _json_object(response)
    stream = cast("dict[str, JsonValue]", payload["stream"])
    audit = AuditLog.objects.get(event_type="usage_stream_resumed")
    assert response.status_code == HTTPStatus.OK
    assert stream["paused"] is False
    assert stream["can_resume"] is False
    assert audit.actor_id == "usage-resume-admin"


def test_usage_stream_resume_when_not_paused() -> None:
    client = _logged_in_superuser("usage-resume-idle-admin")
    _create_runtime(stream_paused=False)

    response = client.post(RESUME_URL)

    payload = _json_object(response)
    error = cast("dict[str, JsonValue]", payload["error"])
    details = cast("dict[str, JsonValue]", error["details"])
    assert response.status_code == HTTPStatus.CONFLICT
    assert details["reason"] == "stream_not_paused"
    assert AuditLog.objects.filter(event_type="usage_stream_resumed").count() == 0


def test_usage_stream_resume_requires_superuser() -> None:
    client = _logged_in_user("usage-resume-user")

    response = client.post(RESUME_URL)

    assert response.status_code == HTTPStatus.FORBIDDEN


def _used_in_range(_metric: str, _start: datetime, _end: datetime, *, billed_only: bool) -> int:
    if billed_only:
        return TODAY_USED["api"]
    return TODAY_USED["api"] + 60


def _breakdown(_start: datetime, _end: datetime) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            metric="api",
            category="notify_send",
            source="easyauth",
            billed=True,
            priority="p1",
            count=12,
            blocked=3,
        ),
    ]


def _timeseries(_start: datetime, _end: datetime, _granularity: str) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            start=datetime(2026, 9, 21, tzinfo=SHANGHAI),
            api_billed=1,
            api_unbilled=0,
            internal=5,
            webhook=0,
            stream=2,
            blocked=0,
        ),
    ]


def _category(key: str) -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        metric="api",
        billed=True,
        priority="p1",
        label_zh="工作通知发送",
        label_en="Work notice send",
    )


def _save_config(state: dict[str, object], config: UsageConfig, *, updated_by: str) -> None:
    state["config"] = config
    row, _created = UsageSettings.objects.get_or_create(
        pk=1,
        defaults={"config": DEFAULT_USAGE_CONFIG, "version": 0, "updated_by": ""},
    )
    row.config = config.model_dump(mode="json")
    row.version += 1
    row.updated_by = updated_by
    row.save()


def _resume_stream(_actor_id: str) -> None:
    row = UsageRuntimeState.objects.get(pk=1)
    row.stream_paused = False
    row.stream_paused_at = None
    row.save(update_fields=["stream_paused", "stream_paused_at"])


def _create_runtime(*, stream_paused: bool, stream_paused_at: datetime | None = None) -> None:
    _ = UsageRuntimeState.objects.create(
        pk=1,
        enforcement={},
        evaluated_at=FROZEN_NOW,
        stream_paused=stream_paused,
        stream_paused_at=stream_paused_at,
        stream_paused_period="2026-09",
        stream_manual_resume_period="",
        authentik_error="",
    )


def _create_alert(
    *,
    kind: str,
    created_at: datetime,
    title: str,
    period_key: str = "2026-09-21",
) -> UsageAlertEvent:
    return UsageAlertEvent.objects.create(
        kind=kind,
        metric="api",
        scope="day",
        period_key=period_key,
        threshold_percent=50,
        status="sent",
        title=title,
        detail="用量越过阈值。",
        failure_reason="",
        created_at=created_at,
    )


def _json_object(response: object) -> dict[str, JsonValue]:
    json_method = response.json
    return cast("dict[str, JsonValue]", json_method())


def _logged_in_superuser(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_admin(client, username)


def _logged_in_user(username: str) -> Client:
    client = Client(HTTP_HOST="localhost")
    return authenticate_console_user(client, username)

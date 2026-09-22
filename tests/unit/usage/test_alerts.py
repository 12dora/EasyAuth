from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from easyauth.accounts.models import USER_STATUS_ACTIVE, DingTalkUserMirror, UserMirror
from easyauth.applications.models import (
    CAPABILITY_NOTIFY,
    App,
    AppCredential,
    AppNotificationChannel,
)
from easyauth.notify.acceptance import NotifyAcceptanceInput
from easyauth.notify.contracts import NotifyAcceptError
from easyauth.usage import alert_delivery
from easyauth.usage.alerts import (
    ALERT_KIND_ANOMALY,
    ALERT_KIND_ENFORCEMENT,
    ALERT_KIND_STREAM_RESUMED,
    ALERT_KIND_THRESHOLD,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SUPERSEDED,
    STATUS_SUPPRESSED,
    record_stream_resumed,
    run,
    sender_status,
)
from easyauth.usage.config import DEFAULT_USAGE_DOCUMENT, UsageConfig
from easyauth.usage.enforcement import EnforcementState, MetricEnforcement
from easyauth.usage.models import UsageAlertEvent, UsageAlertSendBatch

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 9, 21, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
SOURCE = "dingtalk-primary"
CORP = "corp-usage"


def _document() -> dict[str, object]:
    return cast("dict[str, object]", deepcopy(DEFAULT_USAGE_DOCUMENT))


def _section(document: dict[str, object], name: str) -> dict[str, object]:
    section = document[name]
    assert isinstance(section, dict)
    return section


def _config(*, alerts: dict[str, object] | None = None) -> UsageConfig:
    document = _document()
    if alerts is not None:
        _section(document, "alerts").update(alerts)
    return UsageConfig.model_validate(document)


def _state(*, api: str = "normal", stream_paused: bool = False) -> EnforcementState:
    reason = None if api == "normal" else "daily_cap"
    return EnforcementState(
        metrics={
            "api": MetricEnforcement("api", api, reason, NOW),
            "webhook": MetricEnforcement("webhook", "normal", None, None),
            "stream": MetricEnforcement("stream", "normal", None, None),
        },
        evaluated_at=NOW,
        stream_paused=stream_paused,
        stream_paused_period="2026-09-21" if stream_paused else "",
        stream_transition="paused" if stream_paused else None,
    )


def _patch_usage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    day: dict[str, int] | None = None,
    month: dict[str, int] | None = None,
    last_hour: dict[str, int] | None = None,
    baseline: float = 0.0,
) -> None:
    day_map = day or {}
    month_map = month or {}
    hour_map = last_hour or {}
    monkeypatch.setattr("easyauth.usage.alerts.used_today", lambda metric: day_map.get(metric, 0))
    monkeypatch.setattr(
        "easyauth.usage.alerts.used_this_month",
        lambda metric: month_map.get(metric, 0),
    )
    monkeypatch.setattr(
        "easyauth.usage.alerts.current_hour",
        lambda metric: hour_map.get(metric, 0),
    )
    monkeypatch.setattr(
        "easyauth.usage.alerts.baseline_same_hour_avg",
        lambda _metric, **_kwargs: baseline,
    )
    monkeypatch.setattr("easyauth.usage.alerts.day_period_key", lambda _now: "2026-09-21")
    monkeypatch.setattr("easyauth.usage.alerts.month_period_key", lambda _now: "2026-09")


def _silent_send(
    monkeypatch: pytest.MonkeyPatch,
    result: str | None = None,
    *,
    handed_off: bool | None = None,
) -> list[object]:
    captured: list[object] = []
    accepted = result is None if handed_off is None else handed_off

    def _fake(events: object, config: object) -> alert_delivery.MergedAlertDelivery:
        captured.append(events)
        _ = config
        return alert_delivery.MergedAlertDelivery(failure_reason=result, handed_off=accepted)

    monkeypatch.setattr("easyauth.usage.alerts.send_merged_alert", _fake)
    return captured


def _charged_batches() -> int:
    return UsageAlertSendBatch.objects.exclude(batch_key="lock").count()


def test_highest_threshold_sent_lower_superseded(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch)
    _patch_usage(monkeypatch, day={"api": 5000})
    result = run(NOW, _config(), _state())
    assert result.delivered is True
    statuses = {
        event.threshold_percent: event.status
        for event in UsageAlertEvent.objects.filter(kind=ALERT_KIND_THRESHOLD, metric="api")
    }
    assert statuses == {50: STATUS_SUPERSEDED, 80: STATUS_SUPERSEDED, 100: STATUS_SENT}


def test_unique_constraint_dedupe_skips_second_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _silent_send(monkeypatch)
    _patch_usage(monkeypatch, day={"api": 2500})
    first = run(NOW, _config(), _state())
    second = run(NOW, _config(), _state())
    assert first.sent == 1
    assert second.sent == 0
    assert UsageAlertEvent.objects.filter(kind=ALERT_KIND_THRESHOLD).count() == 1
    assert len(captured) == 1


def test_integrity_error_race_treated_as_already_alerted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _silent_send(monkeypatch)
    _patch_usage(monkeypatch, day={"api": 2500})
    _ = UsageAlertEvent.objects.create(
        kind=ALERT_KIND_THRESHOLD,
        metric="api",
        scope="day",
        period_key="2026-09-21",
        threshold_percent=50,
        status=STATUS_SENT,
        title="用量阈值告警",
        detail="already",
        failure_reason="",
    )
    monkeypatch.setattr("easyauth.usage.alerts._existing_event", lambda _draft: None)
    result = run(NOW, _config(), _state())
    assert result.sent == 0
    assert UsageAlertEvent.objects.filter(kind=ALERT_KIND_THRESHOLD).count() == 1


def test_alerts_disabled_stores_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _silent_send(monkeypatch)
    _patch_usage(monkeypatch, day={"api": 5000})
    result = run(NOW, _config(alerts={"enabled": False}), _state())
    assert result.delivered is False
    assert captured == []
    statuses = {
        event.threshold_percent: event.status
        for event in UsageAlertEvent.objects.filter(kind=ALERT_KIND_THRESHOLD, metric="api")
    }
    assert statuses[100] == STATUS_SUPPRESSED
    assert set(statuses.values()) <= {STATUS_SUPPRESSED, STATUS_SUPERSEDED}
    assert STATUS_SENT not in set(UsageAlertEvent.objects.values_list("status", flat=True))


def test_daily_cap_suppresses_beyond_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch)
    _patch_usage(monkeypatch, day={"api": 2500})
    _ = run(NOW, _config(alerts={"daily_cap": 1}), _state())
    _patch_usage(monkeypatch, day={"api": 4000})
    result = run(NOW, _config(alerts={"daily_cap": 1}), _state())
    assert UsageAlertEvent.objects.filter(status=STATUS_SENT).count() == 1
    assert UsageAlertEvent.objects.filter(threshold_percent=80, status=STATUS_SUPPRESSED).exists()
    assert result.delivered is False


def test_enforcement_alert_once_per_period(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch)
    _patch_usage(monkeypatch)
    first = run(NOW, _config(), _state(api="degraded_p2"))
    second = run(NOW, _config(), _state(api="degraded_p2"))
    assert first.sent == 1
    assert second.sent == 0
    assert UsageAlertEvent.objects.filter(kind=ALERT_KIND_ENFORCEMENT).count() == 1


def test_anomaly_respects_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch)
    _patch_usage(monkeypatch, last_hour={"api": 1000}, baseline=100.0)
    first = run(NOW, _config(), _state())
    assert first.sent == 1
    assert UsageAlertEvent.objects.filter(kind=ALERT_KIND_ANOMALY).count() == 1
    later = NOW + timedelta(minutes=10)
    second = run(later, _config(), _state())
    assert second.sent == 0
    _ = UsageAlertEvent.objects.filter(kind=ALERT_KIND_ANOMALY).update(
        created_at=NOW - timedelta(minutes=61),
    )
    third = run(NOW + timedelta(hours=1), _config(), _state())
    assert third.sent == 1


def test_sender_not_ready_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch, result="发送方应用未就绪")
    _patch_usage(monkeypatch, day={"api": 2500})
    result = run(NOW, _config(), _state())
    assert result.delivered is False
    event = UsageAlertEvent.objects.get(kind=ALERT_KIND_THRESHOLD)
    assert event.status == STATUS_FAILED
    assert event.failure_reason == "发送方应用未就绪"


def test_failed_event_retries_after_gap_within_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch, result="发送方应用未就绪")
    _patch_usage(monkeypatch, day={"api": 2500})
    _ = run(NOW, _config(), _state())
    too_soon = run(NOW + timedelta(minutes=9), _config(), _state())
    event = UsageAlertEvent.objects.get(kind=ALERT_KIND_THRESHOLD)
    assert too_soon.delivered is False
    assert event.status == STATUS_FAILED
    assert event.delivery_attempts == 1
    assert event.failure_reason == "发送方应用未就绪"
    _silent_send(monkeypatch, result=None)
    result = run(NOW + timedelta(minutes=10), _config(), _state())
    event.refresh_from_db()
    assert result.delivered is True
    assert event.status == STATUS_SENT
    assert event.failure_reason == ""
    assert event.delivery_attempts == 2


def test_failed_retry_stops_after_three_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _silent_send(monkeypatch, result="发送方应用未就绪")
    _patch_usage(monkeypatch, day={"api": 2500})
    for offset in (0, 10, 20):
        _ = run(NOW + timedelta(minutes=offset), _config(), _state())
    event = UsageAlertEvent.objects.get(kind=ALERT_KIND_THRESHOLD)
    assert len(captured) == 3
    assert event.delivery_attempts == 3
    assert event.status == STATUS_FAILED
    assert event.failure_reason == "发送方应用未就绪"
    later = _silent_send(monkeypatch, result=None)
    result = run(NOW + timedelta(minutes=40), _config(), _state())
    event.refresh_from_db()
    assert result.delivered is False
    assert later == []
    assert event.status == STATUS_FAILED
    assert event.failure_reason == "发送方应用未就绪"
    assert event.delivery_attempts == 3


def test_cap_full_does_not_rewrite_failed_to_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch, result="发送方应用未就绪")
    _patch_usage(monkeypatch, day={"api": 2500})
    _ = run(NOW, _config(alerts={"daily_cap": 1}), _state())
    _ = UsageAlertSendBatch.objects.create(day_key="2026-09-21", batch_key="usage:other")
    _silent_send(monkeypatch, result=None)
    _ = run(NOW + timedelta(minutes=10), _config(alerts={"daily_cap": 1}), _state())
    event = UsageAlertEvent.objects.get(kind=ALERT_KIND_THRESHOLD)
    assert event.status == STATUS_FAILED
    assert event.failure_reason == "发送方应用未就绪"
    assert event.delivery_attempts == 1


def test_daily_cap_charges_one_merged_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch)
    _patch_usage(
        monkeypatch,
        day={"api": 5000},
        last_hour={"api": 1000},
        baseline=100.0,
    )
    first = run(NOW, _config(alerts={"daily_cap": 1}), _state())
    sent_kinds = set(
        UsageAlertEvent.objects.filter(status=STATUS_SENT).values_list("kind", flat=True),
    )
    assert first.delivered is True
    assert ALERT_KIND_THRESHOLD in sent_kinds
    assert ALERT_KIND_ANOMALY in sent_kinds
    assert _charged_batches() == 1
    second = run(NOW, _config(alerts={"daily_cap": 1}), _state(api="degraded_p2"))
    enforcement = UsageAlertEvent.objects.get(kind=ALERT_KIND_ENFORCEMENT)
    assert second.delivered is False
    assert enforcement.status == STATUS_SUPPRESSED
    assert _charged_batches() == 1


def test_handed_off_failure_keeps_one_batch_charge(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch, result="受理失败", handed_off=True)
    _patch_usage(monkeypatch, day={"api": 2500})
    _ = run(NOW, _config(alerts={"daily_cap": 1}), _state())
    assert _charged_batches() == 1
    _silent_send(monkeypatch, result=None)
    result = run(NOW + timedelta(minutes=10), _config(alerts={"daily_cap": 1}), _state())
    event = UsageAlertEvent.objects.get(kind=ALERT_KIND_THRESHOLD)
    assert result.delivered is True
    assert event.status == STATUS_SENT
    assert _charged_batches() == 1


def test_sender_not_ready_does_not_consume_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _silent_send(monkeypatch, result="发送方应用未就绪")
    _patch_usage(monkeypatch, day={"api": 2500})
    _ = run(NOW, _config(), _state())
    assert _charged_batches() == 0


def test_record_stream_resumed_joins_next_merged_send(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _silent_send(monkeypatch)
    _patch_usage(monkeypatch)
    record_stream_resumed(NOW, "2026-09-21")
    record_stream_resumed(NOW, "2026-09-21")
    pending = UsageAlertEvent.objects.get(kind=ALERT_KIND_STREAM_RESUMED)
    assert pending.status == STATUS_FAILED
    assert pending.delivery_attempts == 0
    assert UsageAlertEvent.objects.filter(kind=ALERT_KIND_STREAM_RESUMED).count() == 1
    result = run(NOW, _config(), _state())
    pending.refresh_from_db()
    assert result.delivered is True
    assert pending.status == STATUS_SENT
    assert len(captured) == 1


def test_sender_status_ready_and_recipients() -> None:
    _seed_sender()
    ready, problem, count = sender_status()
    assert ready is True
    assert problem is None
    assert count == 1


def test_sender_status_missing_identity() -> None:
    ready, problem, count = sender_status()
    assert ready is False
    assert problem == "发送方应用未就绪"
    assert count == 0


def test_sender_status_zero_recipients() -> None:
    _seed_sender(with_admin=False)
    ready, problem, count = sender_status()
    assert ready is False
    assert problem == "没有可投递的控制台管理员"
    assert count == 0


def test_merged_message_contains_numbers_and_time(monkeypatch: pytest.MonkeyPatch) -> None:
    accepted: list[object] = []

    def _accept(payload: object) -> object:
        accepted.append(payload)

        class _Result:
            accepted = True
            message = object()

        return _Result()

    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    monkeypatch.setattr(alert_delivery, "accept_notify_message", _accept)
    _seed_sender()
    _patch_usage(monkeypatch, day={"api": 2500})
    result = run(NOW, _config(), _state())
    assert result.delivered is True
    payload = accepted[0]
    assert isinstance(payload, NotifyAcceptanceInput)
    assert payload.message.title == "EasyAuth 用量告警"
    assert "2500/5000" in payload.message.content
    assert "2026-09-21 15:30" in payload.message.content
    assert payload.message.dedup_key.startswith("usage:")
    assert "202609211530" not in payload.message.dedup_key
    assert payload.message.recipients == ("admin-1",)


def test_retry_reuses_dedup_key_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []

    def _accept(payload: object) -> object:
        assert isinstance(payload, NotifyAcceptanceInput)
        seen.append((payload.message.dedup_key, payload.message.content))
        if len(seen) == 1:
            raise NotifyAcceptError(kind="dependency_unavailable", message="通道暂不可用")

        class _Result:
            accepted = True
            message = object()

        return _Result()

    monkeypatch.setattr("django.utils.timezone.now", lambda: NOW)
    monkeypatch.setattr(alert_delivery, "accept_notify_message", _accept)
    _seed_sender()
    _patch_usage(monkeypatch, day={"api": 2500})
    _ = run(NOW, _config(), _state())
    result = run(NOW + timedelta(minutes=10), _config(), _state())
    assert result.delivered is True
    assert seen[0] == seen[1]
    assert seen[0][0].startswith("usage:")
    assert "202609211540" not in seen[0][0]


def _seed_sender(*, with_admin: bool = True) -> App:
    app = App.objects.create(app_key="host-ops", name="主机运维", is_active=True)
    _ = AppCredential.objects.create(
        app=app,
        credential_type="static_token",
        name="告警凭据",
        capabilities=[CAPABILITY_NOTIFY],
        token_hash="not-used",
        token_lookup="0" * 64,
        is_active=True,
    )
    _ = AppNotificationChannel.objects.create(
        app=app,
        name="告警通道",
        dingtalk_app_key="key",
        dingtalk_app_secret="secret",
        agent_id="1001",
        directory_source_slug=SOURCE,
        corp_id=CORP,
        version=1,
        is_active=True,
        created_by="tester",
    )
    if with_admin:
        _ = DingTalkUserMirror.objects.create(
            source_slug=SOURCE,
            corp_id=CORP,
            user_id="dt-admin",
            name="管理员",
            status="active",
        )
        _ = UserMirror.objects.create(
            authentik_user_id="admin-1",
            status=USER_STATUS_ACTIVE,
            is_console_admin=True,
            dingtalk_source_slug=SOURCE,
            dingtalk_userid="dt-admin",
            dingtalk_corp_id=CORP,
        )
    return app

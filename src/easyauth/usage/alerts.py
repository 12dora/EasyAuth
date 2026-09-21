from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal

from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.usage.alert_delivery import send_merged_alert, sender_status
from easyauth.usage.enforcement import QUOTA_METRICS, EnforcementState
from easyauth.usage.models import UsageAlertEvent
from easyauth.usage.queries import (
    baseline_same_hour_avg,
    day_period_key,
    last_60_minutes,
    month_period_key,
    used_this_month,
    used_today,
)

if TYPE_CHECKING:
    from datetime import datetime

    from easyauth.usage.config import AnomalyConfig, QuotaMetric, UsageConfig

__all__ = [
    "ALERT_KIND_ANOMALY",
    "ALERT_KIND_ENFORCEMENT",
    "ALERT_KIND_STREAM_PAUSED",
    "ALERT_KIND_STREAM_RESUMED",
    "ALERT_KIND_THRESHOLD",
    "STATUS_FAILED",
    "STATUS_SENT",
    "STATUS_SUPERSEDED",
    "STATUS_SUPPRESSED",
    "AlertRunResult",
    "run",
    "sender_status",
]

ALERT_KIND_THRESHOLD: Final = "threshold"
ALERT_KIND_ANOMALY: Final = "anomaly"
ALERT_KIND_ENFORCEMENT: Final = "enforcement"
ALERT_KIND_STREAM_PAUSED: Final = "stream_paused"
ALERT_KIND_STREAM_RESUMED: Final = "stream_resumed"
STATUS_SENT: Final = "sent"
STATUS_SUPPRESSED: Final = "suppressed"
STATUS_SUPERSEDED: Final = "superseded"
STATUS_FAILED: Final = "failed"
ANOMALY_BASELINE_DAYS: Final = 7
MONTH_PERIOD_KEY_LENGTH: Final = 7
METRIC_LABEL_ZH: Final[dict[str, str]] = {
    "api": "钉钉出站 API",
    "webhook": "钉钉回调",
    "stream": "钉钉 Stream",
}
STATE_EFFECT_ZH: Final[dict[str, str]] = {
    "normal": "无拦截",
    "degraded_p2": "拦截 P2",
    "degraded_p1": "拦截 P1 与 P2",
    "throttled": "节流 P1/P2",
    "blocked": "拦截全部计费调用",
    "stream_paused": "Stream 已暂停",
}

type _DraftRole = Literal["send", "supersede"]
type _AlertScope = Literal["day", "month", "hour"]


@dataclass(frozen=True, slots=True)
class AlertRunResult:
    created: int
    sent: int
    delivered: bool


@dataclass(frozen=True, slots=True)
class _AlertContext:
    now: datetime
    config: UsageConfig
    state: EnforcementState


@dataclass(frozen=True, slots=True)
class _Draft:
    kind: str
    metric: QuotaMetric
    scope: _AlertScope
    period_key: str
    threshold_percent: int
    title: str
    detail: str
    role: _DraftRole


@dataclass(frozen=True, slots=True)
class _ThresholdScope:
    metric: QuotaMetric
    scope: Literal["day", "month"]
    used: int
    limit: int | None
    thresholds: tuple[int, ...]


def run(now: datetime, config: UsageConfig, state: EnforcementState) -> AlertRunResult:
    ctx = _AlertContext(now=now, config=config, state=state)
    drafts = _collect_drafts(ctx)
    claimed = _claim_drafts(ctx, drafts)
    sendable = tuple(event for event in claimed if event.status == STATUS_SENT)
    if not sendable:
        return AlertRunResult(created=len(claimed), sent=0, delivered=False)
    failure = send_merged_alert(sendable, now, config)
    if failure is None:
        return AlertRunResult(created=len(claimed), sent=len(sendable), delivered=True)
    _mark_failed(sendable, failure)
    return AlertRunResult(created=len(claimed), sent=0, delivered=False)


def _collect_drafts(ctx: _AlertContext) -> list[_Draft]:
    return [
        *_threshold_drafts(ctx),
        *_anomaly_drafts(ctx),
        *_enforcement_drafts(ctx),
        *_stream_drafts(ctx),
    ]


def _threshold_drafts(ctx: _AlertContext) -> list[_Draft]:
    drafts: list[_Draft] = []
    for metric in QUOTA_METRICS:
        drafts.extend(_threshold_metric_drafts(ctx, metric))
    return drafts


def _threshold_metric_drafts(ctx: _AlertContext, metric: QuotaMetric) -> list[_Draft]:
    quota = ctx.config.quota_for(metric)
    day = _ThresholdScope(
        metric=metric,
        scope="day",
        used=used_today(metric),
        limit=quota.daily_cap,
        thresholds=quota.alert_thresholds_percent,
    )
    month = _ThresholdScope(
        metric=metric,
        scope="month",
        used=used_this_month(metric),
        limit=quota.monthly_quota,
        thresholds=quota.alert_thresholds_percent,
    )
    return [*_scope_drafts(ctx, day), *_scope_drafts(ctx, month)]


def _scope_drafts(ctx: _AlertContext, item: _ThresholdScope) -> list[_Draft]:
    limit = item.limit
    if limit is None or limit <= 0:
        return []
    crossed = [value for value in item.thresholds if item.used * 100 >= limit * value]
    if not crossed:
        return []
    highest = max(crossed)
    percent = item.used * 100.0 / limit
    return [_threshold_draft(ctx, item, value, percent, highest) for value in crossed]


def _threshold_draft(
    ctx: _AlertContext,
    item: _ThresholdScope,
    threshold: int,
    percent: float,
    highest: int,
) -> _Draft:
    period = day_period_key(ctx.now) if item.scope == "day" else month_period_key(ctx.now)
    scope_label = "日" if item.scope == "day" else "月"
    effect = _policy_effect(ctx, item.metric)
    detail = (
        f"{METRIC_LABEL_ZH[item.metric]} {scope_label}用量 {item.used}/{item.limit} "
         f"({_format_percent(percent)}), 触及 {threshold}%, 策略效果: {effect}"
    )
    return _Draft(
        kind=ALERT_KIND_THRESHOLD,
        metric=item.metric,
        scope=item.scope,
        period_key=period,
        threshold_percent=threshold,
        title="用量阈值告警",
        detail=detail,
        role="send" if threshold == highest else "supersede",
    )


def _anomaly_drafts(ctx: _AlertContext) -> list[_Draft]:
    drafts: list[_Draft] = []
    for metric in QUOTA_METRICS:
        draft = _anomaly_for_metric(ctx, metric)
        if draft is not None:
            drafts.append(draft)
    return drafts


def _anomaly_for_metric(ctx: _AlertContext, metric: QuotaMetric) -> _Draft | None:
    anomaly = ctx.config.quota_for(metric).anomaly
    count = last_60_minutes(metric)
    if not anomaly.enabled or count < anomaly.baseline_min_calls:
        return None
    if not _anomaly_triggered(anomaly, count, metric):
        return None
    if _anomaly_in_cooldown(ctx, metric):
        return None
    baseline = baseline_same_hour_avg(metric, days=ANOMALY_BASELINE_DAYS)
    period = timezone.localtime(ctx.now).strftime("%Y-%m-%dT%H")
    detail = (
        f"{METRIC_LABEL_ZH[metric]} 近 60 分钟 {count} 次, "
         f"基线(7 日同时段均) {baseline:.1f} 次, 阈值倍数 {anomaly.baseline_multiplier}"
    )
    return _Draft(
        kind=ALERT_KIND_ANOMALY,
        metric=metric,
        scope="hour",
        period_key=period,
        threshold_percent=0,
        title="用量异常告警",
        detail=detail,
        role="send",
    )


def _anomaly_triggered(anomaly: AnomalyConfig, count: int, metric: QuotaMetric) -> bool:
    if anomaly.hourly_absolute is not None and count > anomaly.hourly_absolute:
        return True
    baseline = baseline_same_hour_avg(metric, days=ANOMALY_BASELINE_DAYS)
    return count > anomaly.baseline_multiplier * baseline


def _anomaly_in_cooldown(ctx: _AlertContext, metric: QuotaMetric) -> bool:
    latest = (
        UsageAlertEvent.objects.filter(kind=ALERT_KIND_ANOMALY, metric=metric)
        .order_by("-created_at")
        .first()
    )
    if latest is None:
        return False
    elapsed = ctx.now - latest.created_at
    return elapsed < timedelta(minutes=ctx.config.alerts.cooldown_minutes)


def _enforcement_drafts(ctx: _AlertContext) -> list[_Draft]:
    item = ctx.state.metrics.get("api")
    if item is None or item.state == "normal" or item.reason is None:
        return []
    reason = item.reason
    scope: _AlertScope = "month" if reason == "monthly_quota" else "day"
    period = month_period_key(ctx.now) if scope == "month" else day_period_key(ctx.now)
    detail = (
        f"{METRIC_LABEL_ZH['api']} 进入 {item.state} "
         f"(原因: {reason}), 策略效果: {STATE_EFFECT_ZH[item.state]}"
    )
    return [
        _Draft(
            kind=ALERT_KIND_ENFORCEMENT,
            metric="api",
            scope=scope,
            period_key=period,
            threshold_percent=0,
            title="用量策略变更",
            detail=detail,
            role="send",
        ),
    ]


def _stream_drafts(ctx: _AlertContext) -> list[_Draft]:
    transition = ctx.state.stream_transition
    if transition is None:
        return []
    period = ctx.state.stream_paused_period
    scope = _scope_for_period(period)
    if transition == "paused":
        return [_stream_draft(ALERT_KIND_STREAM_PAUSED, "Stream 已暂停", period, scope)]
    return [_stream_draft(ALERT_KIND_STREAM_RESUMED, "Stream 已恢复", period, scope)]


def _stream_draft(
    kind: str,
    title: str,
    period: str,
    scope: _AlertScope,
) -> _Draft:
    verb = "已暂停" if kind == ALERT_KIND_STREAM_PAUSED else "已恢复"
    return _Draft(
        kind=kind,
        metric="stream",
        scope=scope,
        period_key=period,
        threshold_percent=0,
        title=title,
        detail=f"钉钉 Stream {verb} (周期 {period})",
        role="send",
    )


def _claim_drafts(ctx: _AlertContext, drafts: list[_Draft]) -> list[UsageAlertEvent]:
    remaining = _remaining_budget(ctx)
    claimed: list[UsageAlertEvent] = []
    for draft in drafts:
        status = _status_for_draft(ctx, draft, remaining)
        event = _claim_one(draft, status)
        if event is None:
            continue
        claimed.append(event)
        if event.status == STATUS_SENT:
            remaining = max(0, remaining - 1)
    return claimed


def _status_for_draft(ctx: _AlertContext, draft: _Draft, remaining: int) -> str:
    if draft.role == "supersede":
        return STATUS_SUPERSEDED
    if not ctx.config.alerts.enabled or remaining <= 0:
        return STATUS_SUPPRESSED
    return STATUS_SENT


def _remaining_budget(ctx: _AlertContext) -> int:
    start = timezone.localtime(ctx.now).replace(hour=0, minute=0, second=0, microsecond=0)
    sent = UsageAlertEvent.objects.filter(status=STATUS_SENT, created_at__gte=start).count()
    return max(0, ctx.config.alerts.daily_cap - sent)


def _claim_one(draft: _Draft, status: str) -> UsageAlertEvent | None:
    existing = _existing_event(draft)
    if existing is not None:
        return _reuse_failed(existing, status)
    return _insert_event(draft, status)


def _existing_event(draft: _Draft) -> UsageAlertEvent | None:
    return UsageAlertEvent.objects.filter(
        kind=draft.kind,
        metric=draft.metric,
        scope=draft.scope,
        period_key=draft.period_key,
        threshold_percent=draft.threshold_percent,
    ).first()


def _reuse_failed(existing: UsageAlertEvent, status: str) -> UsageAlertEvent | None:
    if existing.status != STATUS_FAILED:
        return None
    existing.status = status
    existing.failure_reason = ""
    existing.save(update_fields=["status", "failure_reason"])
    return existing


def _insert_event(draft: _Draft, status: str) -> UsageAlertEvent | None:
    try:
        with transaction.atomic():
            return UsageAlertEvent.objects.create(
                kind=draft.kind,
                metric=draft.metric,
                scope=draft.scope,
                period_key=draft.period_key,
                threshold_percent=draft.threshold_percent,
                status=status,
                title=draft.title,
                detail=draft.detail,
                failure_reason="",
            )
    except IntegrityError:
        return None


def _mark_failed(events: tuple[UsageAlertEvent, ...], reason: str) -> None:
    for event in events:
        event.status = STATUS_FAILED
        event.failure_reason = reason
        event.save(update_fields=["status", "failure_reason"])


def _policy_effect(ctx: _AlertContext, metric: QuotaMetric) -> str:
    item = ctx.state.metrics.get(metric)
    if item is None:
        return STATE_EFFECT_ZH["normal"]
    return STATE_EFFECT_ZH[item.state]


def _scope_for_period(period_key: str) -> _AlertScope:
    if len(period_key) == MONTH_PERIOD_KEY_LENGTH:
        return "month"
    if "T" in period_key:
        return "hour"
    return "day"


def _format_percent(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"

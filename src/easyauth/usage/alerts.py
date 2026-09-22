from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from easyauth.usage.alert_delivery import (
    batch_key_for_events,
    batch_key_for_parts,
    send_merged_alert,
    sender_status,
)
from easyauth.usage.enforcement_state import QUOTA_METRICS, EnforcementState
from easyauth.usage.models import UsageAlertEvent, UsageAlertSendBatch
from easyauth.usage.queries import (
    baseline_same_hour_avg,
    current_hour,
    day_period_key,
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
    "record_stream_resumed",
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
MAX_DELIVERY_ATTEMPTS: Final = 3
ORPHAN_RETRY_LIMIT: Final = 20
MIN_RETRY_GAP: Final = timedelta(minutes=10)
LOCK_BATCH_KEY: Final = "lock"
EMPTY_PERIOD_MESSAGE: Final = "Stream 恢复周期不能为空。"
NAIVE_RESUME_MESSAGE: Final = "Stream 恢复时刻必须是带时区的 datetime。"
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


@dataclass(slots=True)
class _Buckets:
    fresh: list[_Draft]
    retries: list[UsageAlertEvent]
    suppressed: list[_Draft]
    superseded: list[_Draft]


@dataclass(frozen=True, slots=True)
class _Classified:
    fresh: tuple[_Draft, ...]
    retries: tuple[UsageAlertEvent, ...]
    suppressed: tuple[_Draft, ...]
    superseded: tuple[_Draft, ...]


@dataclass(frozen=True, slots=True)
class _ThresholdScope:
    metric: QuotaMetric
    scope: Literal["day", "month"]
    used: int
    limit: int | None
    thresholds: tuple[int, ...]


def run(now: datetime, config: UsageConfig, state: EnforcementState) -> AlertRunResult:
    ctx = _AlertContext(now=now, config=config, state=state)
    grouped = _classify(ctx, _collect_drafts(ctx))
    if not grouped.fresh and not grouped.retries:
        parked = _store_terminal(grouped)
        return AlertRunResult(created=len(parked), sent=0, delivered=False)
    if not _cap_open(ctx, grouped):
        return _store_blocked(grouped)
    return _deliver(ctx, grouped)


def record_stream_resumed(now: datetime, period_key: str) -> None:
    # 无独立 pending 状态: failed 且 delivery_attempts=0 表示待下次评估合并发送。
    if timezone.is_naive(now):
        raise ValueError(NAIVE_RESUME_MESSAGE)
    if period_key == "":
        raise ValueError(EMPTY_PERIOD_MESSAGE)
    draft = _stream_draft(
        ALERT_KIND_STREAM_RESUMED,
        "Stream 已恢复",
        period_key,
        _scope_for_period(period_key),
    )
    if _existing_event(draft) is not None:
        return
    _ = _insert_event(draft, STATUS_FAILED)


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
    count = current_hour(metric)
    if not anomaly.enabled or count < anomaly.baseline_min_calls:
        return None
    if not _anomaly_triggered(anomaly, count, metric):
        return None
    if _anomaly_in_cooldown(ctx, metric):
        return None
    baseline = baseline_same_hour_avg(metric, days=ANOMALY_BASELINE_DAYS)
    period = timezone.localtime(ctx.now).strftime("%Y-%m-%dT%H")
    observed = f"{METRIC_LABEL_ZH[metric]} 本小时 {count} 次"
    compared = f"基线(7 日同时段均) {baseline:.1f} 次, 阈值倍数 {anomaly.baseline_multiplier}"
    detail = f"{observed}, {compared}"
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


def _classify(ctx: _AlertContext, drafts: list[_Draft]) -> _Classified:
    buckets = _Buckets(fresh=[], retries=[], suppressed=[], superseded=[])
    for draft in drafts:
        _place_draft(ctx, draft, buckets)
    buckets.retries.extend(_orphan_retries(ctx, buckets.retries))
    return _Classified(
        tuple(buckets.fresh),
        tuple(buckets.retries),
        tuple(buckets.suppressed),
        tuple(buckets.superseded),
    )


def _place_draft(ctx: _AlertContext, draft: _Draft, buckets: _Buckets) -> None:
    existing = _existing_event(draft)
    if existing is not None:
        if ctx.config.alerts.enabled and _retryable(existing, ctx.now):
            buckets.retries.append(existing)
        return
    if draft.role == "supersede":
        buckets.superseded.append(draft)
        return
    if not ctx.config.alerts.enabled:
        buckets.suppressed.append(draft)
        return
    buckets.fresh.append(draft)


def _orphan_retries(
    ctx: _AlertContext,
    matched: list[UsageAlertEvent],
) -> list[UsageAlertEvent]:
    # 待重试事件未必会在本轮再次生成草稿(条件已解除、或手动恢复 Stream 记下的事件)。
    # 间隔必须在 LIMIT 之前过滤, 否则未到期的旧失败行会占满名额。
    if not ctx.config.alerts.enabled:
        return []
    seen = {event.id for event in matched}
    due_at = ctx.now - MIN_RETRY_GAP
    rows = UsageAlertEvent.objects.filter(
        Q(last_attempt_at__isnull=True) | Q(last_attempt_at__lte=due_at),
        status=STATUS_FAILED,
        delivery_attempts__lt=MAX_DELIVERY_ATTEMPTS,
    ).order_by("created_at")[:ORPHAN_RETRY_LIMIT]
    return [row for row in rows if row.id not in seen and _retryable(row, ctx.now)]


def _retryable(event: UsageAlertEvent, now: datetime) -> bool:
    if event.status != STATUS_FAILED:
        return False
    if event.delivery_attempts >= MAX_DELIVERY_ATTEMPTS:
        return False
    last = event.last_attempt_at
    if last is None:
        return True
    return now - last >= MIN_RETRY_GAP


def _store_terminal(grouped: _Classified) -> tuple[UsageAlertEvent, ...]:
    superseded = _insert_drafts(grouped.superseded, STATUS_SUPERSEDED)
    suppressed = _insert_drafts(grouped.suppressed, STATUS_SUPPRESSED)
    return superseded + suppressed


def _store_blocked(grouped: _Classified) -> AlertRunResult:
    parked = _store_terminal(grouped)
    blocked = _insert_drafts(grouped.fresh, STATUS_SUPPRESSED)
    created = len(parked) + len(blocked)
    return AlertRunResult(created=created, sent=0, delivered=False)


def _deliver(ctx: _AlertContext, grouped: _Classified) -> AlertRunResult:
    parked = _store_terminal(grouped)
    created = _insert_drafts(grouped.fresh, STATUS_SENT)
    sendable = grouped.retries + created
    if not sendable:
        return AlertRunResult(created=len(parked), sent=0, delivered=False)
    return _send_events(ctx, sendable, created_count=len(parked) + len(created))


def _send_events(
    ctx: _AlertContext,
    events: tuple[UsageAlertEvent, ...],
    *,
    created_count: int,
) -> AlertRunResult:
    day_key = _day_key(ctx.now)
    batch_key = batch_key_for_events(events)
    reservation = _reserve_send_batch(day_key, batch_key, ctx.config.alerts.daily_cap)
    if reservation == "blocked":
        _suppress_unattempted(events)
        return AlertRunResult(created=created_count, sent=0, delivered=False)
    outcome = send_merged_alert(events, ctx.config)
    if not outcome.handed_off and reservation == "created":
        _release_send_batch(day_key, batch_key)
    _finish_delivery(events, ctx.now, outcome.failure_reason)
    delivered = outcome.handed_off and outcome.failure_reason is None
    sent = len(events) if delivered else 0
    return AlertRunResult(created=created_count, sent=sent, delivered=delivered)


def _cap_open(ctx: _AlertContext, grouped: _Classified) -> bool:
    parts = tuple(_draft_part(draft) for draft in grouped.fresh)
    parts += tuple(_event_part(event) for event in grouped.retries)
    batch_key = batch_key_for_parts(parts)
    return _send_batch_allowed(_day_key(ctx.now), batch_key, ctx.config.alerts.daily_cap)


def _draft_part(draft: _Draft) -> str:
    threshold = draft.threshold_percent
    return f"{draft.kind}:{draft.metric}:{draft.scope}:{draft.period_key}:{threshold}"


def _event_part(event: UsageAlertEvent) -> str:
    threshold = event.threshold_percent
    return f"{event.kind}:{event.metric}:{event.scope}:{event.period_key}:{threshold}"


def _insert_drafts(drafts: tuple[_Draft, ...], status: str) -> tuple[UsageAlertEvent, ...]:
    created: list[UsageAlertEvent] = []
    for draft in drafts:
        event = _insert_event(draft, status)
        if event is not None:
            created.append(event)
    return tuple(created)


def _existing_event(draft: _Draft) -> UsageAlertEvent | None:
    return UsageAlertEvent.objects.filter(
        kind=draft.kind,
        metric=draft.metric,
        scope=draft.scope,
        period_key=draft.period_key,
        threshold_percent=draft.threshold_percent,
    ).first()


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
                delivery_attempts=0,
                last_attempt_at=None,
            )
    except IntegrityError:
        return None


def _suppress_unattempted(events: tuple[UsageAlertEvent, ...]) -> None:
    for event in events:
        if event.status != STATUS_SENT:
            continue
        event.status = STATUS_SUPPRESSED
        event.save(update_fields=["status"])


def _finish_delivery(
    events: tuple[UsageAlertEvent, ...],
    now: datetime,
    failure: str | None,
) -> None:
    status = STATUS_FAILED if failure else STATUS_SENT
    reason = "" if failure is None else failure
    for event in events:
        event.status = status
        event.failure_reason = reason
        event.delivery_attempts = event.delivery_attempts + 1
        event.last_attempt_at = now
        event.save(
            update_fields=[
                "status",
                "failure_reason",
                "delivery_attempts",
                "last_attempt_at",
            ],
        )


def _reserve_send_batch(
    day_key: str,
    batch_key: str,
    cap: int,
) -> Literal["created", "kept", "blocked"]:
    with transaction.atomic():
        _lock_send_day(day_key)
        if _batch_exists(day_key, batch_key):
            return "kept"
        if _charged_batch_count(day_key) >= cap:
            return "blocked"
        _ = UsageAlertSendBatch.objects.create(day_key=day_key, batch_key=batch_key)
        return "created"


def _release_send_batch(day_key: str, batch_key: str) -> None:
    _ = UsageAlertSendBatch.objects.filter(day_key=day_key, batch_key=batch_key).delete()


def _send_batch_allowed(day_key: str, batch_key: str, cap: int) -> bool:
    if _batch_exists(day_key, batch_key):
        return True
    return _charged_batch_count(day_key) < cap


def _lock_send_day(day_key: str) -> None:
    # batch_key=lock 只串行化当日计数, 不代表一条已发送的合并消息。
    _ = UsageAlertSendBatch.objects.select_for_update().get_or_create(
        day_key=day_key,
        batch_key=LOCK_BATCH_KEY,
    )


def _batch_exists(day_key: str, batch_key: str) -> bool:
    return UsageAlertSendBatch.objects.filter(day_key=day_key, batch_key=batch_key).exists()


def _charged_batch_count(day_key: str) -> int:
    rows = UsageAlertSendBatch.objects.filter(day_key=day_key).exclude(batch_key=LOCK_BATCH_KEY)
    return rows.count()


def _day_key(now: datetime) -> str:
    return timezone.localtime(now).date().isoformat()


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

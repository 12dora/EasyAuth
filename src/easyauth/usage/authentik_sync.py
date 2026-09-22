from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Final, cast
from urllib.error import HTTPError, URLError

from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from easyauth.integrations.authentik.directory_client import AuthentikDirectoryError
from easyauth.integrations.authentik.usage_client import (
    AuthentikUsageBucket,
    AuthentikUsageClient,
    as_policy_json,
    utc_z,
)
from easyauth.usage.enforcement import authentik_policy
from easyauth.usage.enforcement_state import EnforcementState, MetricEnforcement
from easyauth.usage.models import UsageBucket, UsageRuntimeState
from easyauth.usage.registry import category

if TYPE_CHECKING:
    from collections.abc import Callable

    from easyauth.usage.config import QuotaMetric
    from easyauth.usage.enforcement_state import EnforcementStateName, LimitReason

logger = logging.getLogger(__name__)

RUNTIME_STATE_PK: Final = 1
PULL_LOOKBACK: Final = timedelta(hours=3)
POLICY_TTL: Final = timedelta(minutes=10)
AUTHENTIK_SOURCE: Final = "authentik"
API_METRIC: Final = "api"
ENFORCEMENT_CACHE_KEY: Final = "usage:enforcement"
DAY_BILLED_CACHE_TTL_SECONDS: Final = 3 * 24 * 60 * 60
PULL_FAILED_PREFIX: Final = "Authentik 用量拉取失败"
PUSH_FAILED_PREFIX: Final = "Authentik 用量策略推送失败"
ENFORCEMENT_MISSING_MESSAGE: Final = "用量执行状态尚未计算, 无法向 Authentik 推送策略。"
ENFORCEMENT_INVALID_MESSAGE: Final = "用量执行状态格式无效, 无法向 Authentik 推送策略。"
_QUOTA_METRICS: Final = frozenset({"api", "webhook", "stream"})
_ENFORCEMENT_STATES: Final = frozenset(
    {"normal", "degraded_p2", "degraded_p1", "throttled", "blocked", "stream_paused"},
)
_LIMIT_REASONS: Final = frozenset({"daily_cap", "monthly_quota"})
CACHE_WRITE_FAILED_LOG: Final = "写入 Authentik 当日计费用量缓存失败。"
AUTHENTIK_RECOVERED_LOG: Final = "Authentik 用量同步已恢复。"
NAIVE_NOW_MESSAGE: Final = "用量同步时刻必须是带时区的 datetime。"
DAY_BILLED_TYPE_MESSAGE: Final = "Authentik 当日计费用量合计类型无效。"
_EXPECTED_SYNC_ERRORS: Final = (
    AuthentikDirectoryError,
    OSError,
    TimeoutError,
    URLError,
    HTTPError,
    ConnectionError,
)


class UsageAuthentikSyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _RuntimePatch:
    authentik_error: str
    authentik_pulled_at: datetime | None = None
    authentik_policy_pushed_at: datetime | None = None


def pull(now: datetime) -> None:
    error, exc = _capture(_pull, now, PULL_FAILED_PREFIX)
    _commit_runtime(
        _RuntimePatch(authentik_error=error, authentik_pulled_at=None if error else now),
        _errors(exc),
    )


def push_policy(now: datetime) -> None:
    error, exc = _capture(_push, now, PUSH_FAILED_PREFIX)
    _commit_runtime(
        _RuntimePatch(
            authentik_error=error,
            authentik_policy_pushed_at=None if error else now,
        ),
        _errors(exc),
    )


def sync(now: datetime) -> None:
    pull_error, pull_exc = _capture(_pull, now, PULL_FAILED_PREFIX)
    push_error, push_exc = _capture(_push, now, PUSH_FAILED_PREFIX)
    _commit_runtime(
        _RuntimePatch(
            authentik_error=_join_errors(pull_error, push_error),
            authentik_pulled_at=None if pull_error else now,
            authentik_policy_pushed_at=None if push_error else now,
        ),
        _errors(pull_exc, push_exc),
    )


def _capture(
    action: Callable[[datetime], None],
    now: datetime,
    prefix: str,
) -> tuple[str, BaseException | None]:
    try:
        action(now)
    except Exception as error:  # noqa: BLE001 - Authentik 同步任何失败只落 authentik_error, 不得抛出 beat 任务.
        return _error_text(prefix, error), error
    return "", None


def _errors(*items: BaseException | None) -> tuple[BaseException, ...]:
    return tuple(item for item in items if item is not None)


def _pull(now: datetime) -> None:
    _require_aware(now)
    report = _usage_client().get_usage(since=_since_on_the_hour(now))
    with transaction.atomic():
        for bucket in report.buckets:
            _upsert_bucket(bucket)
    _store_day_billed_cache(now)


def _push(now: datetime) -> None:
    _require_aware(now)
    policy = authentik_policy(_load_enforcement_state())
    body = as_policy_json(policy)
    body["expires_at"] = utc_z(now.astimezone(UTC) + POLICY_TTL)
    _ = _usage_client().put_usage_policy(body)


def _usage_client() -> AuthentikUsageClient:
    return AuthentikUsageClient.from_settings()


def _since_on_the_hour(now: datetime) -> datetime:
    hour_start = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return hour_start - PULL_LOOKBACK


def _upsert_bucket(item: AuthentikUsageBucket) -> None:
    spec = category(item.category)
    _ = UsageBucket.objects.update_or_create(
        hour_start=item.hour_start,
        source=AUTHENTIK_SOURCE,
        category=item.category,
        defaults={
            "metric": spec.metric,
            "billed": spec.billed,
            "count": item.count,
            "blocked_count": item.blocked_count,
        },
    )


def _store_day_billed_cache(now: datetime) -> None:
    start, end = _local_day_bounds_utc(now)
    totals = UsageBucket.objects.filter(
        source=AUTHENTIK_SOURCE,
        metric=API_METRIC,
        billed=True,
        hour_start__gte=start,
        hour_start__lt=end,
    ).aggregate(total=Sum("count"))
    billed = _sum_as_int(cast("object", totals.get("total")))
    try:
        cache.set(_day_billed_cache_key(now), billed, timeout=DAY_BILLED_CACHE_TTL_SECONDS)
    except Exception as error:  # noqa: BLE001 - 缓存后端异常类型不可枚举, 写失败只记日志.
        logger.warning("%s %s", CACHE_WRITE_FAILED_LOG, error)


def _sum_as_int(raw: object) -> int:
    if raw is None:
        return 0
    if type(raw) is int:
        return raw
    if isinstance(raw, Decimal):
        return int(raw)
    raise UsageAuthentikSyncError(DAY_BILLED_TYPE_MESSAGE)


def _day_billed_cache_key(now: datetime) -> str:
    day_key = timezone.localtime(now).strftime("%Y%m%d")
    return f"usage:day:{day_key}:api_billed_authentik"


def _local_day_bounds_utc(now: datetime) -> tuple[datetime, datetime]:
    local = timezone.localtime(now)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def _load_enforcement_state() -> EnforcementState:
    cached = cast("object", cache.get(ENFORCEMENT_CACHE_KEY))
    if cached is not None:
        return _coerce_enforcement_state(cached)
    row = UsageRuntimeState.objects.filter(pk=RUNTIME_STATE_PK).first()
    enforcement = None if row is None else row.enforcement
    if not enforcement:
        raise UsageAuthentikSyncError(ENFORCEMENT_MISSING_MESSAGE)
    return _coerce_enforcement_state(enforcement)


def _coerce_enforcement_state(raw: object) -> EnforcementState:
    if isinstance(raw, EnforcementState):
        return raw
    if not isinstance(raw, dict):
        raise UsageAuthentikSyncError(ENFORCEMENT_INVALID_MESSAGE)
    payload = cast("dict[str, object]", raw)
    metrics_raw = payload.get("metrics")
    evaluated = _as_optional_datetime(payload.get("evaluated_at"))
    if not isinstance(metrics_raw, dict) or evaluated is None:
        raise UsageAuthentikSyncError(ENFORCEMENT_INVALID_MESSAGE)
    metrics: dict[str, MetricEnforcement] = {}
    for key, value in cast("dict[str, object]", metrics_raw).items():
        item = _as_metric_enforcement(value)
        if item is None:
            continue
        metrics[key] = item
    return EnforcementState(metrics=metrics, evaluated_at=evaluated)


def _as_metric_enforcement(raw: object) -> MetricEnforcement | None:
    if isinstance(raw, MetricEnforcement):
        return raw
    if not isinstance(raw, dict):
        return None
    payload = cast("dict[str, object]", raw)
    metric = _as_quota_metric(payload.get("metric"))
    state = _as_state_name(payload.get("state"))
    if metric is None or state is None:
        return None
    return MetricEnforcement(
        metric=metric,
        state=state,
        reason=_as_limit_reason(payload.get("reason")),
        since=_as_optional_datetime(payload.get("since")),
    )


def _as_quota_metric(value: object) -> QuotaMetric | None:
    if value in _QUOTA_METRICS:
        return cast("QuotaMetric", value)
    return None


def _as_state_name(value: object) -> EnforcementStateName | None:
    if value in _ENFORCEMENT_STATES:
        return cast("EnforcementStateName", value)
    return None


def _as_limit_reason(value: object) -> LimitReason:
    if value in _LIMIT_REASONS:
        return cast("LimitReason", value)
    return None


def _as_optional_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _commit_runtime(patch: _RuntimePatch, errors: tuple[BaseException, ...]) -> None:
    with transaction.atomic():
        _ = UsageRuntimeState.objects.get_or_create(pk=RUNTIME_STATE_PK)
        row = UsageRuntimeState.objects.select_for_update().get(pk=RUNTIME_STATE_PK)
        _log_error_change(row.authentik_error, patch.authentik_error, errors)
        _apply_runtime(row, patch)


def _apply_runtime(row: UsageRuntimeState, patch: _RuntimePatch) -> None:
    row.authentik_error = patch.authentik_error
    fields = ["authentik_error"]
    if patch.authentik_pulled_at is not None:
        row.authentik_pulled_at = patch.authentik_pulled_at
        fields.append("authentik_pulled_at")
    if patch.authentik_policy_pushed_at is not None:
        row.authentik_policy_pushed_at = patch.authentik_policy_pushed_at
        fields.append("authentik_policy_pushed_at")
    row.save(update_fields=fields)


def _log_error_change(previous: str, current: str, errors: tuple[BaseException, ...]) -> None:
    if current == previous:
        return
    if current == "":
        logger.info(AUTHENTIK_RECOVERED_LOG)
        return
    unexpected = _unexpected(errors)
    if unexpected is None:
        logger.warning("%s", current)
        return
    logger.warning("%s", current, exc_info=unexpected)


def _unexpected(errors: tuple[BaseException, ...]) -> BaseException | None:
    for error in errors:
        if isinstance(error, UsageAuthentikSyncError):
            continue
        if isinstance(error, _EXPECTED_SYNC_ERRORS):
            continue
        return error
    return None


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None:
        raise UsageAuthentikSyncError(NAIVE_NOW_MESSAGE)


def _join_errors(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


def _error_text(prefix: str, error: BaseException) -> str:
    return f"{prefix}: {error}"

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from redis.exceptions import RedisError

from easyauth.integrations.dingtalk.errors import DingTalkCallBudgetExceededError

if TYPE_CHECKING:
    from datetime import date

logger = logging.getLogger(__name__)

type DingTalkCallCategory = Literal[
    "token",
    "notify_send",
    "notify_reconcile",
    "robot_send",
    "approval",
    "probe",
]

DINGTALK_CALL_CATEGORIES: Final[tuple[DingTalkCallCategory, ...]] = (
    "token",
    "notify_send",
    "notify_reconcile",
    "robot_send",
    "approval",
    "probe",
)
CALL_BUDGET_TTL_DAYS: Final = 3
CALL_BUDGET_CACHE_TTL_SECONDS: Final = CALL_BUDGET_TTL_DAYS * 24 * 60 * 60
HARD_BUDGET_WARNING_PERCENT: Final = 80
CACHE_KEY_PREFIX: Final = "easyauth:dingtalk:calls"
RECONCILE_CATEGORY: Final[DingTalkCallCategory] = "notify_reconcile"
DAILY_BUDGET_SETTING: Final = "EASYAUTH_DINGTALK_DAILY_CALL_BUDGET"
RECONCILE_BUDGET_SETTING: Final = "EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET"
_ALLOWED_CATEGORIES: Final[frozenset[str]] = frozenset(DINGTALK_CALL_CATEGORIES)

__all__ = (
    "DINGTALK_CALL_CATEGORIES",
    "DingTalkCallBudgets",
    "DingTalkCallCategory",
    "DingTalkCallUsage",
    "budget_health_reason",
    "budget_health_status",
    "format_usage_summary",
    "record_and_check",
    "usage_today",
)


class _CacheMeteringError(Exception):
    pass


_CACHE_BACKEND_ERRORS: Final = (
    OSError,
    ConnectionError,
    TimeoutError,
    NotImplementedError,
    RedisError,
    _CacheMeteringError,
)


@dataclass(frozen=True, slots=True)
class DingTalkCallBudgets:
    total: int
    notify_reconcile: int


@dataclass(frozen=True, slots=True)
class DingTalkCallUsage:
    day: date
    total: int
    by_category: dict[DingTalkCallCategory, int]
    budgets: DingTalkCallBudgets


@dataclass(frozen=True, slots=True)
class _DeniedCall:
    day: date
    category: DingTalkCallCategory
    total: int
    category_count: int
    budgets: DingTalkCallBudgets


def record_and_check(category: DingTalkCallCategory) -> None:
    """在发出 HTTP 之前记账并检查日预算; 超帽则拒绝且不计数。"""
    _validate_category(category)
    budgets = _require_budgets()
    try:
        denied = _reserve_or_deny(category, budgets)
    except _CACHE_BACKEND_ERRORS as error:
        logger.warning("钉钉调用计量缓存失败, 放行本次调用: %s", error)
        return
    if denied is None:
        return
    _log_exceeded_once(denied)
    message = _exceeded_message(denied)
    raise DingTalkCallBudgetExceededError(message)


def usage_today() -> DingTalkCallUsage:
    day = timezone.localdate()
    budgets = _require_budgets()
    by_category: dict[DingTalkCallCategory, int] = {
        category: _read_count(_category_key(day, category)) for category in DINGTALK_CALL_CATEGORIES
    }
    return DingTalkCallUsage(
        day=day,
        total=_read_count(_total_key(day)),
        by_category=by_category,
        budgets=budgets,
    )


def budget_health_status(usage: DingTalkCallUsage) -> Literal["healthy", "warning", "unhealthy"]:
    if usage.total >= usage.budgets.total:
        return "unhealthy"
    if _hard_budget_warning(usage) or _reconcile_exhausted(usage):
        return "warning"
    return "healthy"


def budget_health_reason(usage: DingTalkCallUsage) -> str:
    status = budget_health_status(usage)
    if status == "unhealthy":
        return "钉钉开放平台日调用硬预算已耗尽。"
    if status == "warning" and _reconcile_exhausted(usage):
        return "钉钉工作通知回执对账日预算已耗尽。"
    if status == "warning":
        return "钉钉开放平台日调用量已达硬预算 80%。"
    return ""


def format_usage_summary(usage: DingTalkCallUsage) -> str:
    counts = ", ".join(
        f"{category}={usage.by_category[category]}" for category in DINGTALK_CALL_CATEGORIES
    )
    reconcile = usage.by_category[RECONCILE_CATEGORY]
    return (
        f"今日调用 {usage.total}/{usage.budgets.total} ({counts}); "
        f"回执对账 {reconcile}/{usage.budgets.notify_reconcile}。"
    )


def _validate_category(category: str) -> None:
    if category not in _ALLOWED_CATEGORIES:
        message = f"未知的钉钉调用类别: {category}"
        raise ValueError(message)


def _require_budgets() -> DingTalkCallBudgets:
    return DingTalkCallBudgets(
        total=_require_positive_int_setting(DAILY_BUDGET_SETTING),
        notify_reconcile=_require_positive_int_setting(RECONCILE_BUDGET_SETTING),
    )


def _require_positive_int_setting(name: str) -> int:
    value = cast("object", getattr(settings, name))
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        message = f"{name} 必须是大于 0 的整数。"
        raise TypeError(message)
    return value


def _reserve_or_deny(
    category: DingTalkCallCategory,
    budgets: DingTalkCallBudgets,
) -> _DeniedCall | None:
    day = timezone.localdate()
    total = _read_count(_total_key(day))
    category_count = _read_count(_category_key(day, category))
    if _is_over_budget(
        category,
        total=total,
        category_count=category_count,
        budgets=budgets,
    ):
        return _DeniedCall(
            day=day,
            category=category,
            total=total,
            category_count=category_count,
            budgets=budgets,
        )
    _ = _incr(_total_key(day))
    _ = _incr(_category_key(day, category))
    return None


def _is_over_budget(
    category: DingTalkCallCategory,
    *,
    total: int,
    category_count: int,
    budgets: DingTalkCallBudgets,
) -> bool:
    if total >= budgets.total:
        return True
    return category == RECONCILE_CATEGORY and category_count >= budgets.notify_reconcile


def _hard_budget_warning(usage: DingTalkCallUsage) -> bool:
    return usage.total * 100 >= usage.budgets.total * HARD_BUDGET_WARNING_PERCENT


def _reconcile_exhausted(usage: DingTalkCallUsage) -> bool:
    return usage.by_category[RECONCILE_CATEGORY] >= usage.budgets.notify_reconcile


def _total_key(day: date) -> str:
    return f"{CACHE_KEY_PREFIX}:{day.isoformat()}:total"


def _category_key(day: date, category: DingTalkCallCategory) -> str:
    return f"{CACHE_KEY_PREFIX}:{day.isoformat()}:{category}"


def _exceeded_flag_key(day: date, category: DingTalkCallCategory) -> str:
    return f"{CACHE_KEY_PREFIX}:{day.isoformat()}:exceeded:{category}"


def _read_count(key: str) -> int:
    value = cast("object", cache.get(key))
    if value is None:
        return 0
    return _as_count(value)


def _incr(key: str) -> int:
    try:
        return _as_count(cache.incr(key))
    except ValueError:
        _ = cache.add(key, 0, timeout=CALL_BUDGET_CACHE_TTL_SECONDS)
        try:
            return _as_count(cache.incr(key))
        except ValueError as error:
            message = "钉钉调用计量缓存无法递增。"
            raise _CacheMeteringError(message) from error


def _as_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        message = "钉钉调用计量缓存值非法。"
        raise _CacheMeteringError(message)
    return value


def _log_exceeded_once(denied: _DeniedCall) -> None:
    flag_key = _exceeded_flag_key(denied.day, denied.category)
    try:
        first = cache.add(flag_key, 1, timeout=CALL_BUDGET_CACHE_TTL_SECONDS)
    except _CACHE_BACKEND_ERRORS:
        first = True
    if not first:
        return
    logger.error(
        "钉钉开放平台日调用预算已耗尽 day=%s category=%s total=%s/%s reconcile=%s/%s",
        denied.day.isoformat(),
        denied.category,
        denied.total,
        denied.budgets.total,
        denied.category_count if denied.category == RECONCILE_CATEGORY else "-",
        denied.budgets.notify_reconcile,
    )


def _exceeded_message(denied: _DeniedCall) -> str:
    return (
        "钉钉开放平台日调用预算已耗尽"
        f"(category={denied.category}, day={denied.day.isoformat()}, "
        f"total={denied.total}/{denied.budgets.total}, "
        f"{denied.category}={denied.category_count})。"
    )

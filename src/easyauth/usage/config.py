from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Final, Literal, cast, override

from django.core.cache import cache
from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, field_validator

from easyauth.usage.models import UsageSettings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.usage.models import JsonValue

type QuotaMetric = Literal["api", "webhook", "stream"]
type ApiOverLimitPolicy = Literal["alert_only", "degrade", "throttle", "block_all"]
type WebhookOverLimitPolicy = Literal["alert_only"]
type StreamOverLimitPolicy = Literal["alert_only", "pause_stream"]

CONFIG_CACHE_KEY: Final = "usage:config"
CONFIG_CACHE_TTL_SECONDS: Final = 30
USAGE_SETTINGS_PK: Final = 1
QUOTA_MAX: Final = 1_000_000_000
THRESHOLDS_INVALID_MESSAGE: Final = (
    "alert_thresholds_percent 必须是 1 到 5 个介于 1 与 500 之间的互不相同整数。"
)
THRESHOLD_COUNT_MIN: Final = 1
THRESHOLD_COUNT_MAX: Final = 5
THRESHOLD_PERCENT_MIN: Final = 1
THRESHOLD_PERCENT_MAX: Final = 500
SENDER_APP_KEY_BLANK_MESSAGE: Final = "alerts.sender_app_key 不能为空。"
VERSION_CONFLICT_MESSAGE: Final = "用量设置版本冲突。"

DEFAULT_USAGE_DOCUMENT: Final[dict[str, JsonValue]] = cast("dict[str, JsonValue]", {
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
})


class UsageConfigVersionConflictError(Exception):
    @override
    def __str__(self) -> str:
        return VERSION_CONFLICT_MESSAGE


class AnomalyConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    hourly_absolute: StrictInt | None = Field(ge=1, le=QUOTA_MAX)
    baseline_multiplier: float = Field(ge=1.5, le=100)
    baseline_min_calls: StrictInt = Field(ge=1, le=1_000_000)


class ThrottlePerHour(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    p1: StrictInt = Field(ge=0, le=100000)
    p2: StrictInt = Field(ge=0, le=100000)


class _QuotaFields(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    monthly_quota: StrictInt | None = Field(ge=1, le=QUOTA_MAX)
    daily_cap: StrictInt | None = Field(ge=1, le=QUOTA_MAX)
    alert_thresholds_percent: tuple[int, ...]
    anomaly: AnomalyConfig

    @field_validator("alert_thresholds_percent", mode="before")
    @classmethod
    def normalize_thresholds(cls, value: object) -> tuple[int, ...]:
        return _normalize_thresholds(value)


class ApiMetricConfig(_QuotaFields):
    over_limit_policy: ApiOverLimitPolicy
    degrade_escalation_percent: StrictInt = Field(ge=100, le=1000)
    throttle_per_hour: ThrottlePerHour


class WebhookMetricConfig(_QuotaFields):
    over_limit_policy: WebhookOverLimitPolicy


class StreamMetricConfig(_QuotaFields):
    over_limit_policy: StreamOverLimitPolicy


class AlertsConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    cooldown_minutes: StrictInt = Field(ge=5, le=1440)
    daily_cap: StrictInt = Field(ge=1, le=200)
    sender_app_key: str = Field(min_length=1, max_length=64)

    @field_validator("sender_app_key")
    @classmethod
    def normalize_sender_app_key(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError(SENDER_APP_KEY_BLANK_MESSAGE)
        return normalized


type MetricQuotaConfig = ApiMetricConfig | WebhookMetricConfig | StreamMetricConfig


class UsageConfig(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    api: ApiMetricConfig
    webhook: WebhookMetricConfig
    stream: StreamMetricConfig
    alerts: AlertsConfig

    def quota_for(self, metric: QuotaMetric) -> MetricQuotaConfig:
        if metric == "api":
            return self.api
        if metric == "webhook":
            return self.webhook
        return self.stream




def load() -> UsageConfig:
    cached = _config_from_cached(cast("object", cache.get(CONFIG_CACHE_KEY)))
    if cached is not None:
        return cached
    config = _load_from_db()
    cache.set(CONFIG_CACHE_KEY, as_document(config), CONFIG_CACHE_TTL_SECONDS)
    return config


def save(
    config: UsageConfig,
    *,
    updated_by: str,
    expected_version: int | None = None,
) -> int:
    row = UsageSettings.objects.filter(pk=USAGE_SETTINGS_PK).first()
    current_version = 0 if row is None else row.version
    if expected_version is not None and expected_version != current_version:
        raise UsageConfigVersionConflictError(VERSION_CONFLICT_MESSAGE)
    if row is None:
        row = UsageSettings(pk=USAGE_SETTINGS_PK, version=0)
    row.config = as_document(config)
    row.version = current_version + 1
    row.updated_by = updated_by
    row.save()
    invalidate_cache()
    return row.version


def as_document(config: UsageConfig) -> dict[str, JsonValue]:
    return cast("dict[str, JsonValue]", config.model_dump(mode="json"))


def invalidate_cache() -> None:
    _ = cache.delete(CONFIG_CACHE_KEY)


def _load_from_db() -> UsageConfig:
    row = UsageSettings.objects.filter(pk=USAGE_SETTINGS_PK).first()
    if row is None:
        return DEFAULT_USAGE_CONFIG
    return UsageConfig.model_validate(row.config)


def _config_from_cached(raw: object) -> UsageConfig | None:
    if not isinstance(raw, dict):
        return None
    try:
        return UsageConfig.model_validate(cast("Mapping[str, object]", raw))
    except ValidationError:
        return None


def _normalize_thresholds(value: object) -> tuple[int, ...]:
    # pydantic 只把 ValueError 转成校验错误, 因此类型不符也必须抛 ValueError。
    items = _strict_int_items(value)
    if items is None:
        raise ValueError(THRESHOLDS_INVALID_MESSAGE)
    if not THRESHOLD_COUNT_MIN <= len(items) <= THRESHOLD_COUNT_MAX:
        raise ValueError(THRESHOLDS_INVALID_MESSAGE)
    if any(item < THRESHOLD_PERCENT_MIN or item > THRESHOLD_PERCENT_MAX for item in items):
        raise ValueError(THRESHOLDS_INVALID_MESSAGE)
    if len(set(items)) != len(items):
        raise ValueError(THRESHOLDS_INVALID_MESSAGE)
    return tuple(sorted(items))


def _strict_int_items(value: object) -> list[int] | None:
    if not isinstance(value, list | tuple):
        return None
    items: list[int] = []
    for item in cast("list[object] | tuple[object, ...]", value):
        if isinstance(item, bool) or not isinstance(item, int):
            return None
        items.append(item)
    return items


# 依赖上方校验辅助函数, 必须在模块末尾求值。
DEFAULT_USAGE_CONFIG: Final[UsageConfig] = UsageConfig.model_validate(DEFAULT_USAGE_DOCUMENT)

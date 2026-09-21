from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, Self, cast, override

from easyauth.applications.integration_settings import authentik_runtime_config
from easyauth.integrations.authentik.directory_client import (
    DIRECTORY_INVALID_FORMAT_MESSAGE,
    AuthentikDirectoryClient,
    AuthentikDirectoryUnavailableError,
)

if TYPE_CHECKING:
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson, JsonValue

USAGE_INVALID_MESSAGE: Final = DIRECTORY_INVALID_FORMAT_MESSAGE
UTC_Z_NAIVE_MESSAGE: Final = "用量时间必须是带时区的 datetime。"


@dataclass(frozen=True, slots=True)
class AuthentikUsageBucket:
    hour_start: datetime
    category: str
    count: int
    blocked_count: int


@dataclass(frozen=True, slots=True)
class AuthentikUsageReport:
    generated_at: datetime
    buckets: tuple[AuthentikUsageBucket, ...]


@dataclass(frozen=True, slots=True)
class AuthentikUsageClient(AuthentikDirectoryClient):
    """Authentik 目录源的用量拉取 / 策略下发; HTTP 走目录客户端同一套 base_url/token。"""

    @classmethod
    @override
    def from_settings(cls) -> Self:
        config = authentik_runtime_config()
        return cls(
            base_url=config.base_url,
            api_token=config.api_token,
            source_slug=config.source_slug,
            timeout_seconds=config.timeout_seconds,
        )

    def get_usage(self, *, since: datetime) -> AuthentikUsageReport:
        payload = self._request_json("usage/", query={"since": utc_z(since)})
        return parse_usage_report(payload)

    def put_usage_policy(self, policy: DirectoryJson) -> DirectoryJson:
        return self._request_json("usage-policy/", method="PUT", body=policy)


def utc_z(value: datetime) -> str:
    if value.tzinfo is None:
        raise AuthentikDirectoryUnavailableError(UTC_Z_NAIVE_MESSAGE)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_usage_report(payload: DirectoryJson) -> AuthentikUsageReport:
    generated_at = _parse_aware_datetime(payload.get("generated_at"))
    raw_buckets = payload.get("buckets")
    if not isinstance(raw_buckets, list):
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)
    buckets = tuple(_parse_usage_bucket(item) for item in cast("list[object]", raw_buckets))
    return AuthentikUsageReport(generated_at=generated_at, buckets=buckets)


def _parse_usage_bucket(item: object) -> AuthentikUsageBucket:
    if not isinstance(item, dict):
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)
    payload = cast("DirectoryJson", item)
    category = payload.get("category")
    if not isinstance(category, str) or not category:
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)
    return AuthentikUsageBucket(
        hour_start=_hour_start_utc(_parse_aware_datetime(payload.get("hour_start"))),
        category=category,
        count=_non_negative_int(payload.get("count")),
        blocked_count=_non_negative_int(payload.get("blocked_count")),
    )


def _parse_aware_datetime(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE) from error
    if parsed.tzinfo is None:
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)
    return parsed.astimezone(UTC)


def _hour_start_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _non_negative_int(value: object) -> int:
    if type(value) is not int or value < 0:
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)
    return value


def as_policy_json(value: object) -> DirectoryJson:
    if not isinstance(value, dict):
        raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)
    body: DirectoryJson = {}
    for key, item in cast("dict[str, object]", value).items():
        body[key] = _as_json_value(item)
    return body


def _as_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list):
        return [_as_json_value(item) for item in cast("list[object]", value)]
    if isinstance(value, dict):
        nested: dict[str, JsonValue] = {}
        for key, item in cast("dict[str, object]", value).items():
            nested[key] = _as_json_value(item)
        return nested
    raise AuthentikDirectoryUnavailableError(USAGE_INVALID_MESSAGE)

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Mapping

type UsageMetric = Literal["api", "webhook", "stream", "internal"]
type UsageSource = Literal["easyauth", "authentik"]
type UsagePriority = Literal["p0", "p1", "p2"]

USAGE_METRIC_VALUES: Final[tuple[UsageMetric, ...]] = ("api", "webhook", "stream", "internal")
USAGE_SOURCE_VALUES: Final[tuple[UsageSource, ...]] = ("easyauth", "authentik")
USAGE_PRIORITY_VALUES: Final[tuple[UsagePriority, ...]] = ("p0", "p1", "p2")
SOURCE_EASYAUTH: Final[UsageSource] = "easyauth"
SOURCE_AUTHENTIK: Final[UsageSource] = "authentik"


class UnknownUsageCategoryError(KeyError):
    category_key: str

    def __init__(self, key: str) -> None:
        self.category_key = key
        message = f"未知的用量类别: {key}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class UsageCategory:
    key: str
    metric: UsageMetric
    billed: bool
    priority: UsagePriority | None
    label_zh: str
    label_en: str


def _spec(
    key: str,
    metric: UsageMetric,
    *,
    billed: bool,
    priority: UsagePriority | None,
    labels: tuple[str, str],
) -> UsageCategory:
    return UsageCategory(
        key=key,
        metric=metric,
        billed=billed,
        priority=priority,
        label_zh=labels[0],
        label_en=labels[1],
    )


_SPECS: Final[tuple[UsageCategory, ...]] = (
    _spec("token", "api", billed=False, priority="p0", labels=("换票", "Access token")),
    _spec(
        "probe",
        "api",
        billed=False,
        priority="p2",
        labels=("连通性探针", "Connectivity probe"),
    ),
    _spec(
        "notify_send",
        "api",
        billed=True,
        priority="p1",
        labels=("工作通知发送", "Work notice send"),
    ),
    _spec(
        "robot_send",
        "api",
        billed=True,
        priority="p1",
        labels=("机器人消息发送", "Robot send"),
    ),
    _spec(
        "notify_reconcile",
        "api",
        billed=True,
        priority="p2",
        labels=("工作通知回执对账", "Work notice reconcile"),
    ),
    _spec("approval", "api", billed=True, priority="p0", labels=("审批", "Approval")),
    _spec(
        "stream_open",
        "api",
        billed=True,
        priority="p1",
        labels=("Stream 打开连接", "Stream open"),
    ),
    _spec(
        "webhook_callback",
        "webhook",
        billed=True,
        priority=None,
        labels=("钉钉回调", "DingTalk webhook"),
    ),
    _spec(
        "stream_event",
        "stream",
        billed=True,
        priority=None,
        labels=("Stream 事件", "Stream event"),
    ),
    _spec(
        "internal_authentik_directory",
        "internal",
        billed=False,
        priority=None,
        labels=("Authentik 目录", "Authentik directory"),
    ),
    _spec(
        "internal_authentik_admin",
        "internal",
        billed=False,
        priority=None,
        labels=("Authentik 管理", "Authentik admin"),
    ),
    _spec(
        "internal_authentik_other",
        "internal",
        billed=False,
        priority=None,
        labels=("Authentik 其它", "Authentik other"),
    ),
    _spec(
        "internal_netbird",
        "internal",
        billed=False,
        priority=None,
        labels=("NetBird", "NetBird"),
    ),
    _spec(
        "internal_business_webhook",
        "internal",
        billed=False,
        priority=None,
        labels=("业务应用 Webhook", "Business webhook"),
    ),
    _spec(
        "internal_business_hook",
        "internal",
        billed=False,
        priority=None,
        labels=("业务应用 Hook", "Business hook"),
    ),
    _spec(
        "ak_token",
        "api",
        billed=False,
        priority="p0",
        labels=("Authentik 换票", "Authentik token"),
    ),
    _spec(
        "ak_login",
        "api",
        billed=True,
        priority="p0",
        labels=("Authentik 登录", "Authentik login"),
    ),
    _spec(
        "ak_auth_info",
        "api",
        billed=True,
        priority="p1",
        labels=("Authentik 授权信息", "Authentik auth info"),
    ),
    _spec(
        "ak_directory_incremental",
        "api",
        billed=True,
        priority="p1",
        labels=("Authentik 增量目录", "Authentik directory incremental"),
    ),
    _spec(
        "ak_directory_full",
        "api",
        billed=True,
        priority="p2",
        labels=("Authentik 全量目录", "Authentik directory full"),
    ),
    _spec(
        "ak_allowlist",
        "api",
        billed=True,
        priority="p2",
        labels=("Authentik 白名单遍历", "Authentik allowlist"),
    ),
)


def _build_categories() -> Mapping[str, UsageCategory]:
    built: dict[str, UsageCategory] = {}
    for spec in _SPECS:
        if spec.key in built:
            message = f"用量类别重复注册: {spec.key}"
            raise ValueError(message)
        built[spec.key] = spec
    return MappingProxyType(built)


CATEGORIES: Final[Mapping[str, UsageCategory]] = _build_categories()
CATEGORY_KEYS: Final[tuple[str, ...]] = tuple(CATEGORIES)


def category(key: str) -> UsageCategory:
    spec = CATEGORIES.get(key)
    if spec is None:
        raise UnknownUsageCategoryError(key)
    return spec

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from easyauth.applications.ops_models import (
    DEPENDENCY_AUTHENTIK,
    DEPENDENCY_AUTHENTIK_DIRECTORY,
    DEPENDENCY_CELERY,
    DEPENDENCY_DINGTALK,
    DEPENDENCY_HEALTH_STATUS_UNKNOWN,
    DependencyHealthSnapshot,
)

if TYPE_CHECKING:
    from datetime import datetime

CORE_DEPENDENCIES: Final[tuple[str, ...]] = (
    DEPENDENCY_AUTHENTIK,
    DEPENDENCY_AUTHENTIK_DIRECTORY,
    DEPENDENCY_DINGTALK,
    DEPENDENCY_CELERY,
)
UNKNOWN_HEALTH_SUMMARY: Final = "尚未记录健康快照"
SENSITIVE_SUMMARY: Final = "[已隐藏敏感摘要]"
SENSITIVE_MARKERS: Final[tuple[str, ...]] = (
    "secret",
    "token",
    "password",
    "passwd",
    "pwd",
    "authorization",
    "bearer",
    "credential",
    "api_key",
    "api-key",
    "api key",
    "access_key",
    "access-key",
    "access key",
    "private_key",
    "private-key",
    "private key",
    "密码",
    "密钥",
    "口令",
)


@dataclass(frozen=True, slots=True)
class DependencyHealthItem:
    component: str
    status: str
    last_checked_at: datetime | None
    summary: str
    error_summary: str
    app_key: str | None


class DependencyHealthService:
    @staticmethod
    def latest_items() -> tuple[DependencyHealthItem, ...]:
        latest_by_dependency: dict[str, DependencyHealthSnapshot] = {}
        snapshots = DependencyHealthSnapshot.objects.select_related("app").order_by(
            "dependency",
            "-checked_at",
            "-id",
        )
        for snapshot in snapshots:
            if snapshot.dependency not in latest_by_dependency:
                latest_by_dependency[snapshot.dependency] = snapshot
        return tuple(
            _item_for_snapshot(
                dependency=dependency,
                snapshot=latest_by_dependency.get(dependency),
            )
            for dependency in CORE_DEPENDENCIES
        )


def _item_for_snapshot(
    *,
    dependency: str,
    snapshot: DependencyHealthSnapshot | None,
) -> DependencyHealthItem:
    if snapshot is None:
        return DependencyHealthItem(
            component=dependency,
            status=DEPENDENCY_HEALTH_STATUS_UNKNOWN,
            last_checked_at=None,
            summary=UNKNOWN_HEALTH_SUMMARY,
            error_summary="",
            app_key=None,
        )
    app = snapshot.app
    return DependencyHealthItem(
        component=snapshot.dependency,
        status=snapshot.status,
        last_checked_at=snapshot.checked_at,
        summary=_safe_summary(snapshot.summary),
        error_summary=_safe_summary(snapshot.error_summary),
        app_key=None if app is None else app.app_key,
    )


# 从任意 URL 里剥离 userinfo(user:pass@), 覆盖 redis://:pw@host 这类不含 "password"
# 字面子串的凭据; 以及 Authorization: Bearer <token> 形态。
_URL_CREDENTIALS_RE: Final = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@\s]*@")
_BEARER_RE: Final = re.compile(r"(?i)(bearer\s+)\S+")


def redact_summary(value: str) -> str:
    # 写入边界脱敏: 结构化剥离 URL 凭据与 Bearer token, 不依赖朴素子串黑名单,
    # 保证原始异常/连接串里的密钥不会明文落库。
    redacted = _URL_CREDENTIALS_RE.sub(r"\1", value)
    return _BEARER_RE.sub(r"\1[已隐藏]", redacted)


def _safe_summary(value: str) -> str:
    normalized = value.lower()
    if any(marker in normalized for marker in SENSITIVE_MARKERS):
        return SENSITIVE_SUMMARY
    return value

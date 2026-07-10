from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.utils import timezone

from easyauth.accounts.models import DingTalkDirectorySyncState
from easyauth.applications.dependency_health import DependencyHealthService, redact_summary
from easyauth.applications.health_models import (
    DEPENDENCY_AUTHENTIK,
    DEPENDENCY_AUTHENTIK_DIRECTORY,
    DEPENDENCY_CELERY,
    DEPENDENCY_CONNECTORS,
    DEPENDENCY_DINGTALK,
    DEPENDENCY_HEALTH_STATUS_HEALTHY,
    DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
    DEPENDENCY_HEALTH_STATUS_WARNING,
    DependencyHealthSnapshot,
)
from easyauth.applications.integration_settings import authentik_runtime_config
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
    AuthentikDirectoryPermissionError,
)
from easyauth.integrations.authentik.liveness import check_authentik_liveness

if TYPE_CHECKING:
    from easyauth.applications.dependency_health import DependencyHealthItem
    from easyauth.applications.integration_settings import AuthentikRuntimeConfig

class _CeleryControl(Protocol):
    def ping(self, timeout: float = ...) -> list[dict[str, object]] | None: ...


class _CeleryApp(Protocol):
    control: _CeleryControl


CELERY_PING_TIMEOUT_SECONDS: Final = 1.0
DINGTALK_SYNC_STALE_AFTER: Final = timedelta(hours=1)
DIRECTORY_TOKEN_MISSING_MESSAGE: Final = "未配置 Authentik API token, 无法访问目录 API。"  # noqa: S105 - 提示文案, 非凭据.
DINGTALK_SYNC_MISSING_MESSAGE: Final = "尚未执行钉钉目录同步, 无法评估钉钉数据链路。"
CELERY_NO_WORKER_MESSAGE: Final = "无在线 Celery worker 响应 ping。"


@dataclass(frozen=True, slots=True)
class DependencyCheckResult:
    dependency: str
    status: str
    summary: str
    error_summary: str


def run_dependency_health_checks() -> tuple[DependencyHealthItem, ...]:
    # 对四个核心依赖执行真实探测并落库健康快照, 返回最新健康条目。
    config = authentik_runtime_config()
    results = (
        _check_authentik(config),
        _check_authentik_directory(config),
        _check_dingtalk(),
        _check_celery(),
        _check_connectors(),
    )
    now = timezone.now()
    for result in results:
        # 写入边界脱敏: 原始 summary/error_summary 可能内嵌 broker 连接串等凭据,
        # 必须在落库前剥离, 不能只在展示时用子串黑名单兜底。
        _ = DependencyHealthSnapshot.objects.create(
            dependency=result.dependency,
            status=result.status,
            summary=redact_summary(result.summary),
            error_summary=redact_summary(result.error_summary),
            checked_at=now,
        )
    return DependencyHealthService.latest_items()


def _check_authentik(config: AuthentikRuntimeConfig) -> DependencyCheckResult:
    liveness = check_authentik_liveness(
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
    )
    if liveness.ok:
        return DependencyCheckResult(
            dependency=DEPENDENCY_AUTHENTIK,
            status=DEPENDENCY_HEALTH_STATUS_HEALTHY,
            summary=f"{config.base_url} 存活检查通过: {liveness.detail}",
            error_summary="",
        )
    return DependencyCheckResult(
        dependency=DEPENDENCY_AUTHENTIK,
        status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
        summary=f"{config.base_url or '(未配置)'} 存活检查失败。",
        error_summary=liveness.detail,
    )


def _check_authentik_directory(config: AuthentikRuntimeConfig) -> DependencyCheckResult:
    if not config.api_token:
        return DependencyCheckResult(
            dependency=DEPENDENCY_AUTHENTIK_DIRECTORY,
            status=DEPENDENCY_HEALTH_STATUS_WARNING,
            summary=DIRECTORY_TOKEN_MISSING_MESSAGE,
            error_summary="",
        )
    client = AuthentikDirectoryClient(
        base_url=config.base_url,
        api_token=config.api_token,
        source_slug=config.source_slug,
        timeout_seconds=config.timeout_seconds,
    )
    try:
        status = client.get_status()
    except AuthentikDirectoryPermissionError as error:
        return DependencyCheckResult(
            dependency=DEPENDENCY_AUTHENTIK_DIRECTORY,
            status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
            summary="目录 API 拒绝当前凭据。",
            error_summary=str(error),
        )
    except AuthentikDirectoryError as error:
        return DependencyCheckResult(
            dependency=DEPENDENCY_AUTHENTIK_DIRECTORY,
            status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
            summary="目录 API 探测失败。",
            error_summary=str(error),
        )
    return DependencyCheckResult(
        dependency=DEPENDENCY_AUTHENTIK_DIRECTORY,
        status=DEPENDENCY_HEALTH_STATUS_HEALTHY,
        summary=f"目录 API 可用, 源 {status.source_slug} 同步记录 {len(status.sync)} 条。",
        error_summary="",
    )


def _check_dingtalk() -> DependencyCheckResult:
    # 多 corp 部署下必须评估所有同步状态行 (worst-of 汇总): 一个较新的健康 corp
    # 不能掩盖另一个 corp 的失败或陈旧, 否则 .first() 会漏报真实故障。
    states = tuple(DingTalkDirectorySyncState.objects.order_by("source_slug", "corp_id"))
    if not states:
        return DependencyCheckResult(
            dependency=DEPENDENCY_DINGTALK,
            status=DEPENDENCY_HEALTH_STATUS_WARNING,
            summary=DINGTALK_SYNC_MISSING_MESSAGE,
            error_summary="",
        )

    now = timezone.now()
    errored = [state for state in states if state.error]
    if errored:
        corps = ", ".join(f"{state.source_slug}:{state.corp_id}" for state in errored)
        return DependencyCheckResult(
            dependency=DEPENDENCY_DINGTALK,
            status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
            summary=f"钉钉目录同步存在失败的 corp({corps})。",
            error_summary="; ".join(state.error for state in errored),
        )

    stale = [state for state in states if now - state.last_synced_at > DINGTALK_SYNC_STALE_AFTER]
    if stale:
        corps = ", ".join(
            f"{state.source_slug}:{state.corp_id}@{state.last_synced_at.isoformat()}"
            for state in stale
        )
        return DependencyCheckResult(
            dependency=DEPENDENCY_DINGTALK,
            status=DEPENDENCY_HEALTH_STATUS_WARNING,
            summary=f"钉钉目录同步结果已过期({corps})。",
            error_summary="",
        )

    oldest = min(state.last_synced_at for state in states)
    return DependencyCheckResult(
        dependency=DEPENDENCY_DINGTALK,
        status=DEPENDENCY_HEALTH_STATUS_HEALTHY,
        summary=f"钉钉目录同步正常, 共 {len(states)} 个 corp, 最早同步于 {oldest.isoformat()}。",
        error_summary="",
    )


def _check_connectors() -> DependencyCheckResult:
    # 供给连接器不做主动探测(对账任务已在真实调用外部 API), 只汇总实例健康字段:
    # 连续失败达到阈值判不健康(方案 §3.6), 单次失败先给 warning。
    # 函数内导入: 避免 applications ← connectors 模块级互赖(connectors 依赖 applications)。
    from easyauth.connectors.models import (  # noqa: PLC0415
        SYNC_RUN_STATUS_FAILED,
        ConnectorInstance,
    )
    from easyauth.connectors.services import (  # noqa: PLC0415
        CONNECTOR_UNHEALTHY_FAILURE_THRESHOLD,
    )

    instances = tuple(ConnectorInstance.objects.filter(enabled=True).select_related("app"))
    if not instances:
        return DependencyCheckResult(
            dependency=DEPENDENCY_CONNECTORS,
            status=DEPENDENCY_HEALTH_STATUS_HEALTHY,
            summary="无启用的供给连接器实例。",
            error_summary="",
        )
    failing = [
        instance
        for instance in instances
        if instance.consecutive_failures >= CONNECTOR_UNHEALTHY_FAILURE_THRESHOLD
    ]
    if failing:
        names = ", ".join(f"{item.app.app_key}:{item.connector_key}" for item in failing)
        return DependencyCheckResult(
            dependency=DEPENDENCY_CONNECTORS,
            status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
            summary=f"连接器实例连续对账失败({names})。",
            error_summary="; ".join(item.last_error for item in failing if item.last_error),
        )
    warning = [
        instance for instance in instances if instance.last_status == SYNC_RUN_STATUS_FAILED
    ]
    if warning:
        names = ", ".join(f"{item.app.app_key}:{item.connector_key}" for item in warning)
        return DependencyCheckResult(
            dependency=DEPENDENCY_CONNECTORS,
            status=DEPENDENCY_HEALTH_STATUS_WARNING,
            summary=f"连接器实例最近一轮对账失败({names}), 等待下轮重试。",
            error_summary="; ".join(item.last_error for item in warning if item.last_error),
        )
    return DependencyCheckResult(
        dependency=DEPENDENCY_CONNECTORS,
        status=DEPENDENCY_HEALTH_STATUS_HEALTHY,
        summary=f"{len(instances)} 个连接器实例对账正常。",
        error_summary="",
    )


def _check_celery() -> DependencyCheckResult:
    # 避免非任务路径提前初始化 Celery。
    from easyauth.config.celery import app as celery_app  # noqa: PLC0415

    try:
        replies = cast("_CeleryApp", cast("object", celery_app)).control.ping(
            timeout=CELERY_PING_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 - broker 异常类型不可枚举, 必须整体落为不健康快照.
        return DependencyCheckResult(
            dependency=DEPENDENCY_CELERY,
            status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
            summary="无法连接 Celery broker。",
            error_summary=f"{type(error).__name__}: {error}",
        )
    reply_count = len(replies or [])
    if reply_count == 0:
        return DependencyCheckResult(
            dependency=DEPENDENCY_CELERY,
            status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
            summary=CELERY_NO_WORKER_MESSAGE,
            error_summary="",
        )
    return DependencyCheckResult(
        dependency=DEPENDENCY_CELERY,
        status=DEPENDENCY_HEALTH_STATUS_HEALTHY,
        summary=f"{reply_count} 个 worker 响应 ping。",
        error_summary="",
    )

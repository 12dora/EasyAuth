from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Protocol, cast

from django.utils import timezone

from easyauth.accounts.models import DingTalkDirectorySyncState
from easyauth.applications.dependency_health import DependencyHealthService
from easyauth.applications.health_models import (
    DEPENDENCY_AUTHENTIK,
    DEPENDENCY_AUTHENTIK_DIRECTORY,
    DEPENDENCY_CELERY,
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
    )
    now = timezone.now()
    for result in results:
        _ = DependencyHealthSnapshot.objects.create(
            dependency=result.dependency,
            status=result.status,
            summary=result.summary,
            error_summary=result.error_summary,
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
    state = DingTalkDirectorySyncState.objects.order_by("-last_synced_at").first()
    if state is None:
        return DependencyCheckResult(
            dependency=DEPENDENCY_DINGTALK,
            status=DEPENDENCY_HEALTH_STATUS_WARNING,
            summary=DINGTALK_SYNC_MISSING_MESSAGE,
            error_summary="",
        )
    if state.error:
        return DependencyCheckResult(
            dependency=DEPENDENCY_DINGTALK,
            status=DEPENDENCY_HEALTH_STATUS_UNHEALTHY,
            summary=f"最近一次钉钉目录同步失败({state.source_slug}:{state.corp_id})。",
            error_summary=state.error,
        )
    synced_at = state.last_synced_at.isoformat()
    if timezone.now() - state.last_synced_at > DINGTALK_SYNC_STALE_AFTER:
        return DependencyCheckResult(
            dependency=DEPENDENCY_DINGTALK,
            status=DEPENDENCY_HEALTH_STATUS_WARNING,
            summary=f"钉钉目录同步结果已过期, 最近成功同步于 {synced_at}。",
            error_summary="",
        )
    counters = ", ".join(f"{key}={value}" for key, value in sorted(state.counters.items()))
    detail = f", {counters}" if counters else ""
    return DependencyCheckResult(
        dependency=DEPENDENCY_DINGTALK,
        status=DEPENDENCY_HEALTH_STATUS_HEALTHY,
        summary=f"钉钉目录同步正常, 最近同步于 {synced_at}{detail}。",
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

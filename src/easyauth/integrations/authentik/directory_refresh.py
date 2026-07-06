from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol, cast

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.directory_sync import sync_authentik_dingtalk_directory

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from easyauth.integrations.authentik.directory_payloads import DirectoryJson
    from easyauth.integrations.authentik.directory_sync import AuthentikDirectorySyncResult

# Stream 事件驱动的目录刷新: 先让 Authentik 从钉钉拉最新目录, 等它完成后再跑
# EasyAuth 的镜像同步(含离职检出/撤权/交接单)。等待窗口按小目录(数百人)一次
# 全量同步的耗时上限估计; 超时按目录不可用处理, 交给任务重试与定时兜底。
REFRESH_WAIT_TIMEOUT_SECONDS: Final = 180.0
REFRESH_POLL_INTERVAL_SECONDS: Final = 3.0
REFRESH_TIMEOUT_MESSAGE: Final = "等待 Authentik 钉钉目录同步完成超时。"
REFRESH_UPSTREAM_FAILED_MESSAGE: Final = "Authentik 钉钉目录同步失败。"

AUTHENTIK_SYNC_STATUS_SUCCESS: Final = "success"
AUTHENTIK_SYNC_STATUS_ERROR: Final = "error"


@dataclass(frozen=True, slots=True)
class RefreshWaitPolicy:
    """等待 Authentik 同步完成的节奏参数; sleep/monotonic 可注入以便测试。"""

    timeout_seconds: float = REFRESH_WAIT_TIMEOUT_SECONDS
    poll_interval_seconds: float = REFRESH_POLL_INTERVAL_SECONDS
    sleep: Callable[[float], None] = field(default=time.sleep)
    monotonic: Callable[[], float] = field(default=time.monotonic)


DEFAULT_REFRESH_WAIT_POLICY: Final = RefreshWaitPolicy()


class AuthentikDirectoryRefreshClient(Protocol):
    def get_status(self) -> object: ...

    def trigger_sync(self, corp_id: str) -> None: ...

    def iter_departments(self) -> Iterable[object]: ...

    def iter_users(self) -> Iterable[object]: ...

    def get_user_org(self, corp_id: str, user_id: str) -> object: ...


def refresh_dingtalk_directory(
    client: AuthentikDirectoryRefreshClient,
    corp_id: str,
    *,
    wait_policy: RefreshWaitPolicy = DEFAULT_REFRESH_WAIT_POLICY,
) -> AuthentikDirectorySyncResult:
    # 以 Authentik 自己记录的 finished_at 为基线判断"这次触发的同步已完成",
    # 避免 EasyAuth 与 Authentik 主机时钟偏差造成误判。
    baseline = _corp_finished_at(client, corp_id)
    client.trigger_sync(corp_id)
    _wait_for_sync_completion(client, corp_id, baseline=baseline, policy=wait_policy)
    return sync_authentik_dingtalk_directory(client)


def _wait_for_sync_completion(
    client: AuthentikDirectoryRefreshClient,
    corp_id: str,
    *,
    baseline: str,
    policy: RefreshWaitPolicy,
) -> None:
    deadline = policy.monotonic() + policy.timeout_seconds
    while True:
        entry = _corp_sync_entry(client, corp_id)
        if entry is not None:
            finished_at = _string(entry.get("finished_at"))
            status = _string(entry.get("status"))
            if finished_at and finished_at != baseline:
                if status == AUTHENTIK_SYNC_STATUS_SUCCESS:
                    return
                if status == AUTHENTIK_SYNC_STATUS_ERROR:
                    error = _string(entry.get("error"))
                    message = f"{REFRESH_UPSTREAM_FAILED_MESSAGE}: corp={corp_id} {error}".rstrip()
                    raise AuthentikDirectoryUnavailableError(message)
                # 其余状态(如 running 的中间落库)继续等待, 直到出现终态。
        if policy.monotonic() >= deadline:
            message = f"{REFRESH_TIMEOUT_MESSAGE}: corp={corp_id}"
            raise AuthentikDirectoryUnavailableError(message)
        policy.sleep(policy.poll_interval_seconds)


def _corp_finished_at(client: AuthentikDirectoryRefreshClient, corp_id: str) -> str:
    entry = _corp_sync_entry(client, corp_id)
    return _string(entry.get("finished_at")) if entry is not None else ""


def _corp_sync_entry(
    client: AuthentikDirectoryRefreshClient,
    corp_id: str,
) -> DirectoryJson | None:
    status = client.get_status()
    sync_items = getattr(status, "sync", ())
    if not isinstance(sync_items, tuple):
        return None
    for item in cast("tuple[object, ...]", sync_items):
        if not isinstance(item, dict):
            continue
        entry = cast("DirectoryJson", item)
        if _string(entry.get("corp_id")) == corp_id:
            return entry
    return None


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""

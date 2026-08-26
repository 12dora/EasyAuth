from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from easyauth.integrations.authentik.directory_client import AuthentikDirectoryError

__all__ = [
    "AuthentikDirectorySyncClient",
    "AuthentikDirectorySyncResult",
    "UnsupportedDirectoryStatusError",
    "_DirectorySnapshot",
    "_StatusReconciliation",
]

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.integrations.authentik.directory_contract import CorpSnapshotContract
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson


class UnsupportedDirectoryStatusError(AuthentikDirectoryError):
    # 未知目录状态是数据契约破坏; 归入 AuthentikDirectoryError 让同步任务重试并最终显式失败,
    # 而不是把一整轮离职回收静默跳过。
    pass


class AuthentikDirectorySyncClient(Protocol):
    def get_status(self) -> object: ...

    def iter_departments(self) -> Iterable[object]: ...

    def iter_users(self) -> Iterable[object]: ...

    def get_user_org(self, corp_id: str, user_id: str) -> object: ...


@dataclass(frozen=True, slots=True)
class AuthentikDirectorySyncResult:
    department_count: int
    user_count: int
    org_context_count: int
    sync_state_count: int
    pruned_department_count: int = 0
    tombstoned_user_count: int = 0
    status_applied_count: int = 0
    departed_count: int = 0
    revoked_count: int = 0
    org_fetch_failed_count: int = 0
    offboarding_deferred_count: int = 0


@dataclass(frozen=True, slots=True)
class _DirectorySnapshot:
    source_slug: str
    status: DirectoryJson
    contracts: dict[str, CorpSnapshotContract]
    departments: tuple[DirectoryJson, ...]
    users: tuple[DirectoryJson, ...]
    org_contexts: dict[tuple[str, str], DirectoryJson]
    org_fetch_failures: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class _StatusReconciliation:
    applied_count: int
    departed_count: int
    revoked_count: int
    offboarding_deferred_count: int

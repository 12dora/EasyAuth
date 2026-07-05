from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from celery import shared_task

from easyauth.accounts.services import AuthentikSyncService
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
)
from easyauth.integrations.authentik.directory_sync import sync_authentik_dingtalk_directory

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.integrations.authentik.payloads import AuthentikPayloadInput


class AuthentikPayloadSource(Protocol):
    def iter_payloads(self) -> Iterable[AuthentikPayloadInput]: ...


@dataclass(frozen=True, slots=True)
class StaticAuthentikPayloadSource:
    payloads: tuple[AuthentikPayloadInput, ...]

    def iter_payloads(self) -> Iterable[AuthentikPayloadInput]:
        return self.payloads


@dataclass(frozen=True, slots=True)
class AuthentikScheduledSyncResult:
    synced_count: int
    revoked_count: int


DINGTALK_DIRECTORY_SYNC_TASK_NAME = "easyauth.authentik.sync_dingtalk_directory"


def sync_authentik_users_from_source(
    source: AuthentikPayloadSource,
) -> AuthentikScheduledSyncResult:
    synced_count = 0
    revoked_count = 0
    for payload in source.iter_payloads():
        result = AuthentikSyncService.sync_payload(payload)
        synced_count += 1
        revoked_count += result.revoked_count
    return AuthentikScheduledSyncResult(
        synced_count=synced_count,
        revoked_count=revoked_count,
    )


@shared_task(
    name=DINGTALK_DIRECTORY_SYNC_TASK_NAME,
    autoretry_for=(AuthentikDirectoryError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def sync_dingtalk_directory_task() -> dict[str, int]:
    result = sync_authentik_dingtalk_directory(AuthentikDirectoryClient.from_settings())
    return {
        "department_count": result.department_count,
        "user_count": result.user_count,
        "org_context_count": result.org_context_count,
        "sync_state_count": result.sync_state_count,
        "pruned_department_count": result.pruned_department_count,
        "pruned_user_count": result.pruned_user_count,
        "status_applied_count": result.status_applied_count,
        "departed_count": result.departed_count,
        "revoked_count": result.revoked_count,
        "org_fetch_failed_count": result.org_fetch_failed_count,
    }

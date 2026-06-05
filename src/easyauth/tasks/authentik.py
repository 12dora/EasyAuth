from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from easyauth.accounts.services import AuthentikSyncService

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

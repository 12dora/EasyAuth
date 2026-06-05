from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

from easyauth.audit.models import AuditLog

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.audit.models import JsonObject, JsonValue


@dataclass(frozen=True, slots=True)
class AuditRecord:
    actor_type: str
    actor_id: str
    action: str
    target_type: str
    target_id: str
    metadata: Mapping[str, JsonValue] | None = None


@final
class AuditService:
    @staticmethod
    def record(record: AuditRecord) -> AuditLog:
        stored_metadata: JsonObject = dict(record.metadata) if record.metadata is not None else {}
        return AuditLog.objects.create(
            actor_type=record.actor_type,
            actor_id=record.actor_id,
            event_type=record.action,
            target_type=record.target_type,
            target_id=record.target_id,
            metadata=stored_metadata,
        )

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import F

from easyauth.applications.models import App
from easyauth.audit.services import AuditRecord, AuditService

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.audit.models import JsonValue


APP_CATALOG_VERSION_BUMPED_EVENT = "app_catalog_version_bumped"


@transaction.atomic
def bump_catalog_version(
    app: App,
    *,
    actor_id: str,
    reason: str,
    metadata: Mapping[str, JsonValue] | None = None,
) -> App:
    _ = App.objects.filter(id=app.id).update(catalog_version=F("catalog_version") + 1)
    app.refresh_from_db(fields=["catalog_version", "updated_at"])

    audit_metadata: dict[str, JsonValue] = {
        "app_id": app.id,
        "app_key": app.app_key,
        "catalog_version": app.catalog_version,
        "reason": reason,
    }
    if metadata is not None:
        audit_metadata.update(metadata)

    _ = AuditService.record(
        AuditRecord(
            actor_type="user",
            actor_id=actor_id,
            action=APP_CATALOG_VERSION_BUMPED_EVENT,
            target_type="app",
            target_id=str(app.id),
            metadata=audit_metadata,
        ),
    )
    return app

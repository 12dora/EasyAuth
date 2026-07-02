from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue
    from easyauth.grants.query import ExpandedGrant


def expanded_grant_payload(grant: ExpandedGrant) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "permission": grant.permission,
        "scope": grant.scope,
        "source_type": grant.source_type,
        "source_key": grant.source_key,
    }
    if grant.resolved is not None:
        payload["resolved"] = {
            "user_ids": list(grant.resolved.user_ids),
            "resolver": grant.resolved.resolver,
            "resolved_at": grant.resolved.resolved_at,
        }
    return payload

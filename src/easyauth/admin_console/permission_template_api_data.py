from __future__ import annotations

from collections import Counter
from secrets import token_urlsafe
from typing import TYPE_CHECKING, ClassVar, Final, cast

from django.core.cache import cache
from django.core.signing import BadSignature, TimestampSigner
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from easyauth.api.errors import JsonValue
    from easyauth.applications.models import PermissionTemplateVersion
    from easyauth.applications.permission_templates import TemplateAction

PREVIEW_MAX_AGE_SECONDS: Final = 15 * 60
PREVIEW_SIGNING_CONTEXT: Final = "easyauth.permission-template-preview"
PREVIEW_CACHE_KEY_PREFIX: Final = "easyauth:permission-template-preview:"


class CachedTemplatePreview(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=64)
    template_format: str = Field(min_length=1, max_length=16)
    template: str = Field(min_length=1)


def store_template_preview(payload: CachedTemplatePreview) -> str:
    cache_key = _preview_cache_key(token_urlsafe(32))
    cache.set(cache_key, payload.model_dump_json(), timeout=PREVIEW_MAX_AGE_SECONDS)
    return _preview_signer().sign(cache_key)


def load_template_preview(preview_id: str) -> CachedTemplatePreview | None:
    try:
        cache_key = _preview_signer().unsign(
            preview_id,
            max_age=PREVIEW_MAX_AGE_SECONDS,
        )
        raw_payload = cast("object", cache.get(cache_key))
        if not isinstance(raw_payload, str):
            return None
        return CachedTemplatePreview.model_validate_json(raw_payload)
    except (BadSignature, ValidationError):
        return None


def preview_summary(
    version: int,
    actions: tuple[TemplateAction, ...],
) -> dict[str, JsonValue]:
    action_counts = Counter(action.action for action in actions)
    return {
        "version": version,
        "action_count": len(actions),
        "create_scope_count": action_counts["create_scope"],
        "update_scope_count": action_counts["update_scope"],
        "deactivate_scope_count": action_counts["deactivate_scope"],
        "create_permission_group_count": action_counts["create_permission_group"],
        "update_permission_group_count": action_counts["update_permission_group"],
        "deactivate_permission_group_count": action_counts["deactivate_permission_group"],
        "create_permission_count": action_counts["create_permission"],
        "update_permission_count": action_counts["update_permission"],
        "deactivate_permission_count": action_counts["deactivate_permission"],
        "create_authorization_group_count": action_counts["create_authorization_group"],
        "update_authorization_group_count": action_counts["update_authorization_group"],
        "deactivate_authorization_group_count": action_counts["deactivate_authorization_group"],
        "create_approval_rule_count": action_counts["create_approval_rule"],
        "update_approval_rule_count": action_counts["update_approval_rule"],
        "deactivate_approval_rule_count": action_counts["deactivate_approval_rule"],
        "update_app_count": action_counts["update_app"],
    }


def preview_changes(actions: tuple[TemplateAction, ...]) -> list[JsonValue]:
    return [
        {"action": action.action, "key": action.key, "parent_key": action.parent_key}
        for action in actions
    ]


def template_version_item(template_version: PermissionTemplateVersion) -> dict[str, JsonValue]:
    return {
        "version": template_version.version,
        "status": template_version.status,
        "imported_by": template_version.imported_by,
        "action_count": _template_action_count(template_version),
    }


def _preview_signer() -> TimestampSigner:
    return TimestampSigner(salt=PREVIEW_SIGNING_CONTEXT)


def _preview_cache_key(token: str) -> str:
    return f"{PREVIEW_CACHE_KEY_PREFIX}{token}"


def _template_action_count(template_version: PermissionTemplateVersion) -> int:
    summary = template_version.import_summary
    match summary:
        case {"actions": list() as actions}:
            return len(actions)
        case _:
            return 0

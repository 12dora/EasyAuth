from __future__ import annotations

from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error as Base64DecodeError
from collections import Counter
from typing import TYPE_CHECKING, ClassVar, Final

from django.core.signing import BadSignature, TimestampSigner
from pydantic import BaseModel, ConfigDict, Field, ValidationError

if TYPE_CHECKING:
    from easyauth.admin_console.operation_filters import Page
    from easyauth.api.errors import JsonValue
    from easyauth.applications.models import PermissionTemplateVersion
    from easyauth.applications.permission_templates import TemplateAction

PREVIEW_MAX_AGE_SECONDS: Final = 15 * 60
PREVIEW_SIGNING_CONTEXT: Final = "easyauth.permission-template-preview"


class CachedTemplatePreview(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    app_key: str = Field(min_length=1, max_length=64)
    template_format: str = Field(min_length=1, max_length=16)
    template: str = Field(min_length=1)


def store_template_preview(payload: CachedTemplatePreview) -> str:
    encoded_payload = _encode_preview_payload(payload.model_dump_json())
    return _preview_signer().sign(encoded_payload)


def load_template_preview(preview_id: str) -> CachedTemplatePreview | None:
    try:
        encoded_payload = _preview_signer().unsign(
            preview_id,
            max_age=PREVIEW_MAX_AGE_SECONDS,
        )
        raw_payload = _decode_preview_payload(encoded_payload)
        return CachedTemplatePreview.model_validate_json(raw_payload)
    except (BadSignature, Base64DecodeError, UnicodeDecodeError, ValidationError):
        return None


def preview_summary(
    version: int,
    actions: tuple[TemplateAction, ...],
) -> dict[str, JsonValue]:
    action_counts = Counter(action.action for action in actions)
    return {
        "version": version,
        "action_count": len(actions),
        "create_group_count": action_counts["create_group"],
        "create_permission_count": action_counts["create_permission"],
        "update_group_count": action_counts["update_group"],
        "update_permission_count": action_counts["update_permission"],
        "move_permission_count": action_counts["move_permission"],
        "deprecate_permission_count": action_counts["deprecate_permission"],
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


def template_version_pagination_item(
    page: Page[PermissionTemplateVersion],
) -> dict[str, JsonValue]:
    return {
        "page": page.page,
        "page_size": page.page_size,
        "total_items": page.total_items,
        "total_pages": page.total_pages,
    }


def _preview_signer() -> TimestampSigner:
    return TimestampSigner(salt=PREVIEW_SIGNING_CONTEXT)


def _encode_preview_payload(raw_payload: str) -> str:
    return urlsafe_b64encode(raw_payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_preview_payload(encoded_payload: str) -> str:
    padding_length = (-len(encoded_payload)) % 4
    padded_payload = f"{encoded_payload}{'=' * padding_length}"
    return urlsafe_b64decode(padded_payload.encode("ascii")).decode("utf-8")


def _template_action_count(template_version: PermissionTemplateVersion) -> int:
    summary = template_version.import_summary
    match summary:
        case {"actions": list() as actions}:
            return len(actions)
        case _:
            return 0

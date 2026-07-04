from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easyauth.admin_console.catalog_write_common import semantic_response
from easyauth.applications.models import PermissionGroup

if TYPE_CHECKING:
    from django.http import JsonResponse


@dataclass(frozen=True, slots=True)
class ResolvedGroupReference:
    group_id: int | None
    touched: bool


@dataclass(frozen=True, slots=True)
class GroupReferenceInput:
    app_id: int
    key_value: str | None
    key_is_set: bool
    missing_message: str


def resolve_group_reference(
    reference: GroupReferenceInput,
) -> ResolvedGroupReference | JsonResponse:
    if not reference.key_is_set or reference.key_value is None:
        return ResolvedGroupReference(group_id=None, touched=reference.key_is_set)
    group = PermissionGroup.objects.filter(
        app_id=reference.app_id,
        key=reference.key_value,
    ).first()
    if group is None:
        return semantic_response(reference.missing_message)
    return ResolvedGroupReference(group_id=group.id, touched=True)

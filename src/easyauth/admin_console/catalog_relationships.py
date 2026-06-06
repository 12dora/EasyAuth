from __future__ import annotations

from dataclasses import dataclass

from django.http import JsonResponse

from easyauth.admin_console.catalog_write_common import bad_request, semantic_response
from easyauth.applications.models import PermissionGroup


@dataclass(frozen=True, slots=True)
class ResolvedGroupReference:
    group_id: int | None
    touched: bool


@dataclass(frozen=True, slots=True)
class GroupReferenceInput:
    app_id: int
    id_value: int | None
    key_value: str | None
    id_is_set: bool
    key_is_set: bool
    missing_message: str


def resolve_group_reference(
    reference: GroupReferenceInput,
) -> ResolvedGroupReference | JsonResponse:
    if not reference.id_is_set and not reference.key_is_set:
        return ResolvedGroupReference(group_id=None, touched=False)
    match _reference_id(reference):
        case int() as group_id:
            return ResolvedGroupReference(group_id=group_id, touched=True)
        case None:
            return ResolvedGroupReference(group_id=None, touched=True)
        case JsonResponse() as response:
            return response


def _reference_id(reference: GroupReferenceInput) -> int | JsonResponse | None:
    match _group_id_from_key(
        app_id=reference.app_id,
        key_value=reference.key_value,
        key_is_set=reference.key_is_set,
        missing_message=reference.missing_message,
    ):
        case int() as key_group_id:
            pass
        case None:
            key_group_id = None
        case JsonResponse() as response:
            return response
    match _group_id_from_id(
        app_id=reference.app_id,
        id_value=reference.id_value,
        id_is_set=reference.id_is_set,
        missing_message=reference.missing_message,
    ):
        case int() as id_group_id:
            pass
        case None:
            id_group_id = None
        case JsonResponse() as response:
            return response
    if reference.id_is_set and reference.key_is_set and id_group_id != key_group_id:
        return bad_request("关系 id 与 key 指向不同对象。")
    if reference.key_is_set:
        return key_group_id
    return id_group_id


def _group_id_from_key(
    *,
    app_id: int,
    key_value: str | None,
    key_is_set: bool,
    missing_message: str,
) -> int | JsonResponse | None:
    if not key_is_set or key_value is None:
        return None
    group = PermissionGroup.objects.filter(app_id=app_id, key=key_value).first()
    if group is None:
        return semantic_response(missing_message)
    return group.id


def _group_id_from_id(
    *,
    app_id: int,
    id_value: int | None,
    id_is_set: bool,
    missing_message: str,
) -> int | JsonResponse | None:
    if not id_is_set or id_value is None:
        return None
    group = PermissionGroup.objects.filter(id=id_value, app_id=app_id).first()
    if group is None:
        return semantic_response(missing_message)
    return group.id

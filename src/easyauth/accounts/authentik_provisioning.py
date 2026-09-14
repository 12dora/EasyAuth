from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast
from urllib.error import URLError

from django.core.cache import cache

from easyauth.accounts.models import UserMirror
from easyauth.accounts.services import AuthentikSyncService
from easyauth.integrations.authentik.admin_client import (
    AuthentikAdminClient,
    AuthentikAdminError,
)
from easyauth.integrations.authentik.payloads import (
    IS_ACTIVE_BOOLEAN_REASON,
    IS_ACTIVE_FIELD,
    SUBJECT_REQUIRED_REASON,
    AuthentikPayloadError,
)

if TYPE_CHECKING:
    from easyauth.integrations.authentik.admin_client import AdminJson
    from easyauth.integrations.authentik.payloads import (
        AuthentikPayloadInput,
        AuthentikPayloadValue,
    )

logger = logging.getLogger(__name__)

_PROVISION_MISS_CACHE_TTL_SECONDS: Final = 60
_PROVISION_MISS_CACHE_KEY_PREFIX: Final = "authentik-provision-miss:"
_PROVISION_MISS_SENTINEL: Final = 1
_CORE_USER_ATTRIBUTE_KEYS: Final = ("dingtalk", "dingtalk_org", "avatar", "department", "status")
_UUID_FIELD: Final = "uuid"
_ATTRIBUTES_FIELD: Final = "user.attributes"
_DINGTALK_ATTRIBUTE_FIELD: Final = "user.attributes.dingtalk"
_MUST_BE_OBJECT: Final = "must be an object"
_MUST_BE_STRING: Final = "must be a string"
_MUST_BE_JSON: Final = "must be json-compatible"


@dataclass(frozen=True, slots=True)
class MirrorAuthentikUsersResult:
    scanned: int
    created: int
    skipped_no_directory_identity: int
    skipped_existing: int


def authentik_payload_from_core_user(entry: AdminJson) -> AuthentikPayloadInput:
    payload: AuthentikPayloadInput = {"context": {"sub": _core_user_uuid(entry)}}
    user = _core_user_section(entry)
    if user:
        payload["user"] = user
    if "is_active" in entry:
        is_active = entry["is_active"]
        if not isinstance(is_active, bool):
            raise AuthentikPayloadError(IS_ACTIVE_FIELD, IS_ACTIVE_BOOLEAN_REASON)
        payload["is_active"] = is_active
    return payload


def provision_user_from_authentik(sub: str) -> UserMirror | None:
    existing = UserMirror.objects.filter(authentik_user_id=sub).first()
    if existing is not None:
        return existing
    cache_key = _provision_miss_cache_key(sub)
    if cache.get(cache_key) is not None:
        return None
    entry = _fetch_core_user_for_provision(sub, cache_key=cache_key)
    if entry is None:
        return None
    if not _core_user_has_directory_identity(entry):
        _remember_provision_miss(cache_key)
        return None
    return AuthentikSyncService.sync_payload(authentik_payload_from_core_user(entry)).user


def ensure_user_mirror_for_permission_query(user_id: str) -> bool:
    if UserMirror.objects.filter(authentik_user_id=user_id).exists():
        return False
    user = provision_user_from_authentik(user_id)
    if user is None:
        return False
    logger.info("权限查询 JIT 已供给 UserMirror: sub=%s", user_id)
    return True


def mirror_missing_authentik_users(client: AuthentikAdminClient) -> MirrorAuthentikUsersResult:
    existing = set(UserMirror.objects.values_list("authentik_user_id", flat=True))
    scanned = 0
    created = 0
    skipped_no_directory_identity = 0
    skipped_existing = 0
    for entry in client.iter_active_users():
        scanned += 1
        outcome = _mirror_missing_entry(entry, existing=existing)
        if outcome == "created":
            created += 1
        elif outcome == "existing":
            skipped_existing += 1
        else:
            skipped_no_directory_identity += 1
    return MirrorAuthentikUsersResult(
        scanned=scanned,
        created=created,
        skipped_no_directory_identity=skipped_no_directory_identity,
        skipped_existing=skipped_existing,
    )


def _mirror_missing_entry(entry: AdminJson, *, existing: set[str]) -> str:
    uuid = _core_user_uuid(entry)
    if uuid in existing:
        return "existing"
    if not _core_user_has_directory_identity(entry):
        return "no_directory"
    user = AuthentikSyncService.sync_payload(authentik_payload_from_core_user(entry)).user
    existing.add(user.authentik_user_id)
    return "created"


def _fetch_core_user_for_provision(sub: str, *, cache_key: str) -> AdminJson | None:
    try:
        return AuthentikAdminClient.from_settings().get_user_by_uuid(sub)
    except (AuthentikAdminError, URLError) as error:
        logger.warning("Authentik JIT 供给失败, 跳过: sub=%s error=%s", sub, error)
        _remember_provision_miss(cache_key)
        return None


def _core_user_has_directory_identity(entry: AdminJson) -> bool:
    attributes = entry.get("attributes")
    if attributes is None:
        return False
    if not isinstance(attributes, dict):
        raise AuthentikPayloadError(_ATTRIBUTES_FIELD, _MUST_BE_OBJECT)
    typed_attributes = cast("dict[str, object]", attributes)
    if "dingtalk" not in typed_attributes:
        return False
    dingtalk = typed_attributes["dingtalk"]
    if dingtalk is None:
        return False
    if not isinstance(dingtalk, dict):
        raise AuthentikPayloadError(_DINGTALK_ATTRIBUTE_FIELD, _MUST_BE_OBJECT)
    return bool(cast("dict[str, object]", dingtalk))


def _core_user_uuid(entry: AdminJson) -> str:
    uuid = entry.get("uuid")
    if not isinstance(uuid, str) or uuid == "":
        raise AuthentikPayloadError(_UUID_FIELD, SUBJECT_REQUIRED_REASON)
    return uuid


def _core_user_section(entry: AdminJson) -> dict[str, AuthentikPayloadValue]:
    user: dict[str, AuthentikPayloadValue] = {}
    _put_optional_string(user, entry, "name", "user.name")
    _put_optional_string(user, entry, "email", "user.email")
    attributes = _core_user_attributes(entry)
    if attributes:
        user["attributes"] = attributes
    return user


def _core_user_attributes(entry: AdminJson) -> dict[str, AuthentikPayloadValue]:
    raw = entry.get("attributes")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise AuthentikPayloadError(_ATTRIBUTES_FIELD, _MUST_BE_OBJECT)
    attributes = cast("dict[str, object]", raw)
    copied: dict[str, AuthentikPayloadValue] = {}
    for key in _CORE_USER_ATTRIBUTE_KEYS:
        if key not in attributes:
            continue
        value = attributes[key]
        if _is_empty_payload_value(value):
            continue
        copied[key] = _as_payload_value(value, f"user.attributes.{key}")
    return copied


def _put_optional_string(
    target: dict[str, AuthentikPayloadValue],
    entry: AdminJson,
    key: str,
    field_name: str,
) -> None:
    if key not in entry:
        return
    value = _optional_core_string(entry[key], field_name)
    if value is not None:
        target[key] = value


def _optional_core_string(value: object, field_name: str) -> str | None:
    match value:
        case None:
            return None
        case str() as string_value:
            return None if string_value == "" else string_value
        case _:
            raise AuthentikPayloadError(field_name, _MUST_BE_STRING)


def _is_empty_payload_value(value: object) -> bool:
    return value is None or value in ("", {})


def _as_payload_value(value: object, field_name: str) -> AuthentikPayloadValue:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dict):
        return _as_payload_object(cast("dict[object, object]", value), field_name)
    if isinstance(value, list):
        return [_as_payload_value(item, field_name) for item in cast("list[object]", value)]
    raise AuthentikPayloadError(field_name, _MUST_BE_JSON)


def _as_payload_object(
    mapping: dict[object, object],
    field_name: str,
) -> dict[str, AuthentikPayloadValue]:
    payload: dict[str, AuthentikPayloadValue] = {}
    for raw_key, item in mapping.items():
        if not isinstance(raw_key, str):
            raise AuthentikPayloadError(field_name, _MUST_BE_OBJECT)
        payload[raw_key] = _as_payload_value(item, f"{field_name}.{raw_key}")
    return payload


def _provision_miss_cache_key(sub: str) -> str:
    return f"{_PROVISION_MISS_CACHE_KEY_PREFIX}{sub}"


def _remember_provision_miss(cache_key: str) -> None:
    cache.set(cache_key, _PROVISION_MISS_SENTINEL, timeout=_PROVISION_MISS_CACHE_TTL_SECONDS)

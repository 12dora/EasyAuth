from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import TYPE_CHECKING, Final, cast
from urllib.error import HTTPError, URLError

from django.core.cache import cache
from django.db import IntegrityError

from easyauth.accounts.models import UserMirror
from easyauth.accounts.services import AuthentikSyncService
from easyauth.integrations.authentik.admin_client import (
    ADMIN_API_UNAVAILABLE_MESSAGE,
    OPERATION_TIMEOUT_MESSAGE,
    AuthentikAdminClient,
    AuthentikAdminError,
    AuthentikAdminNotConfiguredError,
    AuthentikAdminUserNotFoundError,
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
_PROVISION_UNAVAILABLE_CACHE_KEY: Final = "authentik-provision-unavailable"
_PROVISION_UNAVAILABLE_CACHE_TTL_SECONDS: Final = 30
_PROVISION_UNAVAILABLE_SENTINEL: Final = 1
_HTTP_SERVER_ERROR_MIN: Final = 500
_CORE_USER_ATTRIBUTE_KEYS: Final = ("dingtalk", "dingtalk_org", "avatar", "department", "status")
_UUID_FIELD: Final = "uuid"
_ATTRIBUTES_FIELD: Final = "user.attributes"
_DINGTALK_ATTRIBUTE_FIELD: Final = "user.attributes.dingtalk"
_MUST_BE_OBJECT: Final = "must be an object"
_MUST_BE_STRING: Final = "must be a string"
_MUST_BE_JSON: Final = "must be json-compatible"
USER_PROVISION_UNAVAILABLE_MESSAGE: Final = "Authentik 管理 API 暂不可用, 无法即时建档。"


@unique
class ProvisionKind(StrEnum):
    CREATED = "created"
    EXISTING = "existing"
    NOT_ELIGIBLE = "not_eligible"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class ProvisionOutcome:
    kind: ProvisionKind
    user: UserMirror | None = None


@dataclass(frozen=True, slots=True)
class MirrorAuthentikUsersResult:
    scanned: int
    created: int
    skipped_no_directory_identity: int
    skipped_existing: int


class UserProvisionUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(USER_PROVISION_UNAVAILABLE_MESSAGE)


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


def provision_user_from_authentik(sub: str) -> ProvisionOutcome:
    existing = UserMirror.objects.filter(authentik_user_id=sub).first()
    if existing is not None:
        return ProvisionOutcome(kind=ProvisionKind.EXISTING, user=existing)
    if _provision_unavailable_breaker_set():
        return ProvisionOutcome(kind=ProvisionKind.UNAVAILABLE)
    cache_key = _provision_miss_cache_key(sub)
    if cache.get(cache_key) is not None:
        return ProvisionOutcome(kind=ProvisionKind.NOT_FOUND)
    fetched = _fetch_core_user_for_provision(sub)
    if isinstance(fetched, ProvisionKind):
        return _negative_outcome(fetched, cache_key=cache_key)
    return _sync_core_user(sub, fetched, cache_key=cache_key)


def ensure_user_mirror_for_permission_query(user_id: str) -> bool:
    outcome = provision_user_from_authentik(user_id)
    if outcome.kind is ProvisionKind.UNAVAILABLE:
        raise UserProvisionUnavailableError
    if outcome.kind is ProvisionKind.CREATED:
        logger.info("权限查询 JIT 已供给 UserMirror: sub=%s", user_id)
        return True
    return False


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


def _sync_core_user(sub: str, entry: AdminJson, *, cache_key: str) -> ProvisionOutcome:
    try:
        if not _core_user_has_directory_identity(entry):
            _remember_provision_miss(cache_key)
            return ProvisionOutcome(kind=ProvisionKind.NOT_ELIGIBLE)
        user = AuthentikSyncService.sync_payload(authentik_payload_from_core_user(entry)).user
    except AuthentikPayloadError as error:
        return _invalid_outcome(sub, cache_key=cache_key, error=error)
    except IntegrityError as error:
        raced = UserMirror.objects.filter(authentik_user_id=sub).first()
        if raced is not None:
            return ProvisionOutcome(kind=ProvisionKind.EXISTING, user=raced)
        return _invalid_outcome(sub, cache_key=cache_key, error=error)
    return ProvisionOutcome(kind=ProvisionKind.CREATED, user=user)


def _mirror_missing_entry(entry: AdminJson, *, existing: set[str]) -> str:
    uuid = _core_user_uuid(entry)
    if uuid in existing or _mirror_already_exists(uuid, existing=existing):
        return "existing"
    if not _core_user_has_directory_identity(entry):
        return "no_directory"
    try:
        user = AuthentikSyncService.sync_payload(authentik_payload_from_core_user(entry)).user
    except AuthentikPayloadError:
        logger.exception("Authentik 周期镜像载荷无效: uuid=%s", uuid)
        return "no_directory"
    except IntegrityError:
        # 与登录/JIT 建档并发: 行已存在则按既有处理, 否则是绑定冲突, 记录后跳过。
        if _mirror_already_exists(uuid, existing=existing):
            return "existing"
        logger.exception("Authentik 周期镜像写入冲突: uuid=%s", uuid)
        return "no_directory"
    existing.add(user.authentik_user_id)
    return "created"


def _mirror_already_exists(uuid: str, *, existing: set[str]) -> bool:
    if not UserMirror.objects.filter(authentik_user_id=uuid).exists():
        return False
    existing.add(uuid)
    return True


def _fetch_core_user_for_provision(sub: str) -> AdminJson | ProvisionKind:
    try:
        return AuthentikAdminClient.from_settings().get_user_by_uuid(sub)
    except AuthentikAdminUserNotFoundError as error:
        logger.warning("Authentik JIT 供给未找到用户: sub=%s error=%s", sub, error)
        return ProvisionKind.NOT_FOUND
    except AuthentikAdminNotConfiguredError as error:
        logger.warning("Authentik JIT 供给跳过: sub=%s error=%s", sub, error)
        return ProvisionKind.NOT_ELIGIBLE
    except (AuthentikAdminError, URLError, TimeoutError) as error:
        if _is_transient_admin_failure(error):
            logger.warning("Authentik JIT 供给暂不可用: sub=%s error=%s", sub, error)
            _remember_provision_unavailable()
            return ProvisionKind.UNAVAILABLE
        logger.exception("Authentik JIT 供给数据无效: sub=%s", sub)
        return ProvisionKind.INVALID


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
    identity = cast("dict[str, object]", dingtalk)
    return (
        _nonempty_identity_string(identity.get("source_slug"))
        and _nonempty_identity_string(identity.get("corp_id"))
        and _nonempty_identity_string(identity.get("user_id"))
    )


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
        copied: dict[str, AuthentikPayloadValue] = {}
    elif not isinstance(raw, dict):
        raise AuthentikPayloadError(_ATTRIBUTES_FIELD, _MUST_BE_OBJECT)
    else:
        attributes = cast("dict[str, object]", raw)
        copied = {}
        for key in _CORE_USER_ATTRIBUTE_KEYS:
            if key not in attributes:
                continue
            value = attributes[key]
            if _is_empty_payload_value(value):
                continue
            copied[key] = _as_payload_value(value, f"user.attributes.{key}")
    if "avatar" not in copied and "avatar" in entry:
        avatar = _optional_core_string(entry["avatar"], "avatar")
        if avatar is not None:
            copied["avatar"] = avatar
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


def _nonempty_identity_string(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _is_transient_admin_failure(error: BaseException) -> bool:
    if isinstance(error, TimeoutError):
        return True
    if isinstance(error, HTTPError):
        return error.code >= _HTTP_SERVER_ERROR_MIN
    if isinstance(error, URLError):
        return True
    if not isinstance(error, AuthentikAdminError) or isinstance(
        error, AuthentikAdminUserNotFoundError | AuthentikAdminNotConfiguredError
    ):
        return False
    message = str(error)
    cause = error.__cause__
    return (
        message in {ADMIN_API_UNAVAILABLE_MESSAGE, OPERATION_TIMEOUT_MESSAGE}
        or (cause is not None and cause is not error and _is_transient_admin_failure(cause))
        or "HTTP 5" in message
    )


def _negative_outcome(kind: ProvisionKind, *, cache_key: str) -> ProvisionOutcome:
    if kind is ProvisionKind.UNAVAILABLE:
        return ProvisionOutcome(kind=kind)
    _remember_provision_miss(cache_key)
    return ProvisionOutcome(kind=kind)


def _invalid_outcome(sub: str, *, cache_key: str, error: BaseException) -> ProvisionOutcome:
    logger.error("Authentik JIT 供给数据无效: sub=%s error=%s", sub, error)
    _remember_provision_miss(cache_key)
    return ProvisionOutcome(kind=ProvisionKind.INVALID)


def _provision_miss_cache_key(sub: str) -> str:
    return f"{_PROVISION_MISS_CACHE_KEY_PREFIX}{sub}"


def _remember_provision_miss(cache_key: str) -> None:
    cache.set(cache_key, _PROVISION_MISS_SENTINEL, timeout=_PROVISION_MISS_CACHE_TTL_SECONDS)


def _provision_unavailable_breaker_set() -> bool:
    return cache.get(_PROVISION_UNAVAILABLE_CACHE_KEY) is not None


def _remember_provision_unavailable() -> None:
    cache.set(
        _PROVISION_UNAVAILABLE_CACHE_KEY,
        _PROVISION_UNAVAILABLE_SENTINEL,
        timeout=_PROVISION_UNAVAILABLE_CACHE_TTL_SECONDS,
    )

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import TYPE_CHECKING, Final, cast

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    USER_STATUS_DISABLED,
)
from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryError,
    AuthentikDirectoryUnavailableError,
)
from easyauth.integrations.authentik.directory_contract import (
    DIRECTORY_CONTRACT_MESSAGE,
    assert_directory_payloads,
    assert_org_context,
    directory_user_key,
    status_contract,
)
from easyauth.integrations.authentik.directory_sync_types import (
    AuthentikDirectorySyncClient,
    UnsupportedDirectoryStatusError,
    _DirectorySnapshot,
)

if TYPE_CHECKING:
    from easyauth.accounts.status import UserStatus
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

__all__ = [
    "_directory_source_slug",
    "_directory_user_status",
    "_fetch_directory_snapshot",
    "_int",
    "_keys_for_corps",
    "_list",
    "_mapping",
    "_object_corp_id",
    "_org_contexts_for_corps",
    "_payloads_for_corps",
    "_string",
]

DIRECTORY_STATUS_TO_USER_STATUS: Final[dict[str, str]] = {
    "active": USER_STATUS_ACTIVE,
    "inactive": USER_STATUS_DISABLED,
    "disabled": USER_STATUS_DISABLED,
    "deleted": USER_STATUS_DEPARTED,
    "departed": USER_STATUS_DEPARTED,
}
UNSUPPORTED_DIRECTORY_STATUS_ERROR: Final = "钉钉目录用户状态无法识别。"
DIRECTORY_ORG_CONTEXT_UNAVAILABLE_MESSAGE: Final = "钉钉目录组织上下文拉取失败。"
DIRECTORY_GENERATION_CHANGED_MESSAGE: Final = "钉钉目录 generation 在快照拉取期间发生变化。"


def _fetch_directory_snapshot(client: AuthentikDirectorySyncClient) -> _DirectorySnapshot:
    status = _mapping(client.get_status())
    source_slug, contracts = status_contract(status)
    departments = tuple(_mapping(item) for item in _iter_objects(client.iter_departments()))
    users = tuple(_mapping(item) for item in _iter_objects(client.iter_users()))
    assert_directory_payloads(
        source_slug=source_slug,
        contracts=contracts,
        departments=departments,
        users=users,
        status_validator=_directory_user_status,
    )
    org_contexts: dict[tuple[str, str], DirectoryJson] = {}
    org_fetch_failures: list[tuple[str, str]] = []
    for user_payload in users:
        corp_id, user_id = directory_user_key(user_payload)
        if not (corp_id and user_id):
            continue
        try:
            org_context = _mapping(client.get_user_org(corp_id, user_id))
            assert_org_context(org_context, source_slug=source_slug, key=(corp_id, user_id))
            org_contexts[(corp_id, user_id)] = org_context
        except AuthentikDirectoryError:
            # 单个用户的 org 拉取失败不得中止整轮同步; 隔离该用户、聚合失败并继续。
            org_fetch_failures.append((corp_id, user_id))
    if org_fetch_failures:
        # 组织上下文是主管链和管理范围解析的必需事实; 任何用户缺失都不得推进整代 generation。
        raise AuthentikDirectoryUnavailableError(DIRECTORY_ORG_CONTEXT_UNAVAILABLE_MESSAGE)
    final_status = _mapping(client.get_status())
    final_source_slug, final_contracts = status_contract(final_status)
    if final_source_slug != source_slug or final_contracts != contracts:
        raise AuthentikDirectoryUnavailableError(DIRECTORY_GENERATION_CHANGED_MESSAGE)
    return _DirectorySnapshot(
        source_slug=source_slug,
        status=final_status,
        contracts=contracts,
        departments=departments,
        users=users,
        org_contexts=org_contexts,
        org_fetch_failures=tuple(org_fetch_failures),
    )


def _object_corp_id(item: object) -> str:
    return _string(_mapping(item).get("corp_id"))


def _payloads_for_corps(
    payloads: tuple[DirectoryJson, ...],
    corp_ids: frozenset[str],
) -> tuple[DirectoryJson, ...]:
    return tuple(item for item in payloads if _string(item.get("corp_id")) in corp_ids)


def _org_contexts_for_corps(
    contexts: dict[tuple[str, str], DirectoryJson],
    corp_ids: frozenset[str],
) -> dict[tuple[str, str], DirectoryJson]:
    return {key: value for key, value in contexts.items() if key[0] in corp_ids}


def _keys_for_corps(
    keys: tuple[tuple[str, str], ...],
    corp_ids: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    return tuple(key for key in keys if key[0] in corp_ids)


def _directory_source_slug(payload: DirectoryJson) -> str:
    source_slug = _string(payload.get("source_slug"))
    if source_slug == "":
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
    return source_slug


def _directory_user_status(payload: DirectoryJson) -> UserStatus:
    status_text = _string(payload.get("status"))
    mapped = DIRECTORY_STATUS_TO_USER_STATUS.get(status_text)
    if mapped is None:
        message = f"{UNSUPPORTED_DIRECTORY_STATUS_ERROR}: {status_text!r}"
        raise UnsupportedDirectoryStatusError(message)
    return cast("UserStatus", mapped)


def _iter_objects(value: object) -> tuple[object, ...]:
    if isinstance(value, tuple):
        return cast("tuple[object, ...]", value)
    if isinstance(value, list):
        return tuple(cast("list[object]", value))
    if isinstance(value, dict | str | bytes):
        return (cast("object", value),)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _mapping(value: object) -> DirectoryJson:
    if isinstance(value, dict):
        return cast("DirectoryJson", value)
    if is_dataclass(value):
        return cast("DirectoryJson", asdict(value))  # pyright: ignore[reportArgumentType]
    return {}


def _list(value: object) -> list[object]:
    if isinstance(value, list):
        return cast("list[object]", value)
    if isinstance(value, tuple):
        return list(cast("tuple[object, ...]", value))
    return []


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int:
    return value if isinstance(value, int) else 0

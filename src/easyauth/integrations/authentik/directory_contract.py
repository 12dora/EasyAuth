from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from easyauth.integrations.authentik.directory_client import AuthentikDirectoryUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

DIRECTORY_CONTRACT_MESSAGE: Final = "钉钉目录响应不满足权威快照契约。"


@dataclass(frozen=True, slots=True)
class CorpSnapshotContract:
    generation: int
    user_count: int
    department_count: int


def directory_user_key(payload: DirectoryJson) -> tuple[str, str]:
    return (_string(payload.get("corp_id")), _string(payload.get("user_id")))


def status_contract(
    status: DirectoryJson,
) -> tuple[str, dict[str, CorpSnapshotContract]]:
    source_slug = _string(status.get("source_slug"))
    sync_items = status.get("sync")
    if source_slug == "" or not isinstance(sync_items, list | tuple) or not sync_items:
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)

    contracts: dict[str, CorpSnapshotContract] = {}
    for raw_item in sync_items:
        corp_id, contract = _sync_item_contract(raw_item, known_corp_ids=contracts)
        contracts[corp_id] = contract
    return source_slug, contracts


def _sync_item_contract(
    raw_item: object,
    *,
    known_corp_ids: dict[str, CorpSnapshotContract],
) -> tuple[str, CorpSnapshotContract]:
    if not isinstance(raw_item, dict):
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
    sync = cast("DirectoryJson", raw_item)
    corp_id = _string(sync.get("corp_id"))
    generation = sync.get("generation")
    counters = sync.get("counters")
    if (
        corp_id == ""
        or corp_id in known_corp_ids
        or sync.get("status") != "success"
        or type(generation) is not int
        or generation < 0
        or not isinstance(counters, dict)
    ):
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
    users, departments = _contract_counts(counters)
    return corp_id, CorpSnapshotContract(
        generation=generation,
        user_count=users,
        department_count=departments,
    )


def _contract_counts(counters: DirectoryJson) -> tuple[int, int]:
    users = counters.get("users")
    departments = counters.get("departments")
    if type(users) is not int or users < 0 or type(departments) is not int or departments < 0:
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
    return users, departments


def assert_directory_payloads(
    *,
    source_slug: str,
    contracts: dict[str, CorpSnapshotContract],
    departments: tuple[DirectoryJson, ...],
    users: tuple[DirectoryJson, ...],
    status_validator: Callable[[DirectoryJson], object],
) -> None:
    seen_departments = _assert_department_payloads(
        source_slug=source_slug,
        contracts=contracts,
        departments=departments,
    )
    seen_users = _assert_user_payloads(
        source_slug=source_slug,
        contracts=contracts,
        users=users,
        status_validator=status_validator,
    )
    for corp_id, contract in contracts.items():
        if (
            len(seen_users[corp_id]) != contract.user_count
            or len(seen_departments[corp_id]) != contract.department_count
        ):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)


def _assert_department_payloads(
    *,
    source_slug: str,
    contracts: dict[str, CorpSnapshotContract],
    departments: tuple[DirectoryJson, ...],
) -> dict[str, set[str]]:
    seen_departments: dict[str, set[str]] = {corp_id: set() for corp_id in contracts}
    for department in departments:
        corp_id = _string(department.get("corp_id"))
        dept_id = _string(department.get("dept_id"))
        item_source_slug = _string(department.get("source_slug"))
        if (
            corp_id not in contracts
            or dept_id == ""
            or (item_source_slug and item_source_slug != source_slug)
            or dept_id in seen_departments[corp_id]
        ):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
        seen_departments[corp_id].add(dept_id)
    return seen_departments


def _assert_user_payloads(
    *,
    source_slug: str,
    contracts: dict[str, CorpSnapshotContract],
    users: tuple[DirectoryJson, ...],
    status_validator: Callable[[DirectoryJson], object],
) -> dict[str, set[str]]:
    seen_users: dict[str, set[str]] = {corp_id: set() for corp_id in contracts}
    for user in users:
        corp_id, user_id = directory_user_key(user)
        item_source_slug = _string(user.get("source_slug"))
        if (
            corp_id not in contracts
            or user_id == ""
            or (item_source_slug and item_source_slug != source_slug)
            or user_id in seen_users[corp_id]
        ):
            raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)
        _ = status_validator(user)
        seen_users[corp_id].add(user_id)
    return seen_users


def assert_org_context(
    payload: DirectoryJson,
    *,
    source_slug: str,
    key: tuple[str, str],
) -> None:
    item_source_slug = _string(payload.get("source_slug"))
    if (
        directory_user_key(payload) != key
        or (item_source_slug and item_source_slug != source_slug)
        or not isinstance(payload.get("departments"), list | tuple)
        or not isinstance(payload.get("manager"), dict)
        or not isinstance(payload.get("manager_chain"), list | tuple)
        or type(payload.get("stale")) is not bool
    ):
        raise AuthentikDirectoryUnavailableError(DIRECTORY_CONTRACT_MESSAGE)

def _string(value: object) -> str:
    return value if isinstance(value, str) else ""

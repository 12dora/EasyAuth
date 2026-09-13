"""交接载荷中的人员引用: PersonRef 形状, 不含 HTTP 身份逻辑。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.accounts.department_paths import department_path_labels
from easyauth.accounts.models import UserMirror
from easyauth.accounts.person_payload import person_payload

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from easyauth.api.errors import JsonValue
    from easyauth.lifecycle.models import HandoverTask

type JsonObject = dict[str, "JsonValue"]

__all__ = [
    "_created_by_person",
    "_person_or_none",
    "_users_by_ids",
    "handover_list_people",
    "user_ref",
]


def user_ref(
    user: UserMirror | None,
    *,
    include_status: bool = False,
    department_labels: Mapping[str, str] | None = None,
) -> JsonObject | None:
    if user is None:
        return None
    labels = department_labels if department_labels is not None else department_path_labels((user,))
    payload: JsonObject = person_payload(user, labels)
    if include_status:
        payload["status"] = user.status
        payload["email"] = user.email
    return payload


def _users_by_ids(user_ids: Iterable[str]) -> dict[str, UserMirror]:
    unique_ids = tuple(dict.fromkeys(user_id for user_id in user_ids if user_id))
    if not unique_ids:
        return {}
    return {
        user.authentik_user_id: user
        for user in UserMirror.objects.filter(authentik_user_id__in=unique_ids)
    }


def _person_or_none(
    user_id: str,
    *,
    people: Mapping[str, UserMirror],
    department_labels: Mapping[str, str],
) -> JsonObject | None:
    user = people.get(user_id)
    if user is None:
        return None
    return person_payload(user, department_labels)


def handover_list_people(
    tasks: Sequence[HandoverTask],
) -> tuple[dict[str, UserMirror], dict[str, str]]:
    """列表页一次解析 subject/assignee/created_by 的部门路径。"""
    related: list[UserMirror] = []
    created_by_ids: list[str] = []
    for task in tasks:
        related.append(task.subject_user)
        if task.assignee is not None:
            related.append(task.assignee)
        if task.created_by:
            created_by_ids.append(task.created_by)
    people = {user.authentik_user_id: user for user in related}
    missing = tuple(user_id for user_id in dict.fromkeys(created_by_ids) if user_id not in people)
    if missing:
        people.update(_users_by_ids(missing))
    return people, department_path_labels(people.values())


def _created_by_person(
    task: HandoverTask,
    *,
    people: Mapping[str, UserMirror] | None,
    department_labels: Mapping[str, str] | None,
) -> JsonObject | None:
    if not task.created_by:
        return None
    if people is None:
        resolved = _users_by_ids((task.created_by,))
        return _person_or_none(
            task.created_by,
            people=resolved,
            department_labels=department_path_labels(resolved.values()),
        )
    labels: Mapping[str, str] = department_labels if department_labels is not None else {}
    return _person_or_none(
        task.created_by,
        people=people,
        department_labels=labels,
    )

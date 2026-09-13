"""申请决定人姓名的批量解析: 门户与控制台共用, 缺行策略显式传入。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override

from easyauth.accounts.models import UserMirror

if TYPE_CHECKING:
    from easyauth.access_requests.models import AccessRequest

type MissingDecisionActorPolicy = Literal["raise", "empty"]

MISSING_DECISION_ACTOR_RAISE: Final = "raise"
MISSING_DECISION_ACTOR_EMPTY: Final = "empty"

__all__ = [
    "MISSING_DECISION_ACTOR_EMPTY",
    "MISSING_DECISION_ACTOR_RAISE",
    "AccessRequestDecisionActorMissingError",
    "decided_by_names",
]


@dataclass(frozen=True, slots=True)
class AccessRequestDecisionActorMissingError(RuntimeError):
    missing_user_ids: tuple[str, ...]

    @override
    def __str__(self) -> str:
        missing = list(self.missing_user_ids)
        return f"user-actor access request decisions are missing UserMirror rows: {missing}"


def decided_by_names(
    access_requests: tuple[AccessRequest, ...],
    *,
    actor_types: frozenset[str] | None = None,
    missing: MissingDecisionActorPolicy,
) -> dict[int, str]:
    """批量解析 decided_by 对应的 UserMirror.name。

    actor_types:
      None — 任意非空 decided_by (控制台运营列表)
      frozenset — 仅这些 decision_actor_type (门户「我的申请」只解析 user)
    missing:
      raise — 缺 UserMirror 即失败 (门户: 用户决定人必须能解析)
      empty — 缺行写空字符串 (控制台: 代审 id 可能不是人员主键)
    """
    actor_ids = _actor_ids(access_requests, actor_types)
    names_by_user_id = _names_by_user_id(actor_ids)
    if missing == MISSING_DECISION_ACTOR_RAISE:
        missing_user_ids = tuple(
            actor_id for actor_id in actor_ids if actor_id not in names_by_user_id
        )
        if missing_user_ids:
            raise AccessRequestDecisionActorMissingError(missing_user_ids)
        return {
            access_request.id: names_by_user_id[access_request.decided_by]
            for access_request in access_requests
            if _matches_actor_types(access_request, actor_types)
        }
    return {
        access_request.id: names_by_user_id.get(access_request.decided_by, "")
        if access_request.decided_by
        else ""
        for access_request in access_requests
    }


def _actor_ids(
    access_requests: tuple[AccessRequest, ...],
    actor_types: frozenset[str] | None,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            access_request.decided_by
            for access_request in access_requests
            if _include_actor_id(access_request, actor_types)
        ),
    )


def _include_actor_id(
    access_request: AccessRequest,
    actor_types: frozenset[str] | None,
) -> bool:
    if actor_types is None:
        return bool(access_request.decided_by)
    return _matches_actor_types(access_request, actor_types)


def _matches_actor_types(
    access_request: AccessRequest,
    actor_types: frozenset[str] | None,
) -> bool:
    if actor_types is None:
        return True
    return access_request.decision_actor_type in actor_types


def _names_by_user_id(actor_ids: tuple[str, ...]) -> dict[str, str]:
    if not actor_ids:
        return {}
    return {
        user.authentik_user_id: user.name
        for user in UserMirror.objects.filter(authentik_user_id__in=actor_ids)
    }

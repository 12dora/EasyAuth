"""交接单聚合状态计算(01 §2.2)。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.lifecycle.models import (
    ACTION_FINISHED_STATUSES,
    ACTION_INITIAL_STATUSES,
    ITEM_STATUS_PENDING,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_PENDING,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.lifecycle.models import HandoverAppAction, HandoverTask, HandoverTeamItem


def compute_task_status(
    task: HandoverTask,
    actions: Iterable[HandoverAppAction],
    team_items: Iterable[HandoverTeamItem],
    *,
    plan_confirmed: bool,
) -> str:
    """全量纯函数: 含 in_progress → pending 回退(01 §2.2)。"""
    if task.status == TASK_STATUS_CANCELLED:
        return TASK_STATUS_CANCELLED
    action_list = list(actions)
    team_list = list(team_items)
    if _actions_finished(action_list) and _teams_finished(team_list) and plan_confirmed:
        return TASK_STATUS_COMPLETED
    return TASK_STATUS_IN_PROGRESS if _has_started(action_list, team_list) else TASK_STATUS_PENDING


def _actions_finished(actions: list[HandoverAppAction]) -> bool:
    return all(action.status in ACTION_FINISHED_STATUSES for action in actions)


def _teams_finished(team_items: list[HandoverTeamItem]) -> bool:
    return all(item.status != ITEM_STATUS_PENDING for item in team_items)


def _has_started(
    actions: list[HandoverAppAction],
    team_items: list[HandoverTeamItem],
) -> bool:
    actions_started = any(action.status not in ACTION_INITIAL_STATUSES for action in actions)
    teams_started = any(item.status != ITEM_STATUS_PENDING for item in team_items)
    return actions_started or teams_started

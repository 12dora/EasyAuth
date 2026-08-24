from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.db import transaction
from django.utils import timezone

from easyauth.lifecycle import grant_transfer as _grant_transfer
from easyauth.lifecycle import transfer_diff as _transfer_diff
from easyauth.lifecycle.core import (
    HANDOVER_DATA_NOT_COMPLETED_MESSAGE,
    TRANSFER_CONFIRMATION_CONFLICT_MESSAGE,
    TRANSFER_PLAN_REVISION_CONFLICT_MESSAGE,
    TRANSFER_TASK_REQUIRED_MESSAGE,
    TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE,
    ensure_task_open,
    ensure_transfer_task_open,
    record_task_event,
    refresh_task_status,
)
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.lease import action_execution_in_flight
from easyauth.lifecycle.models import (
    ACTION_FINISHED_STATUSES,
    HANDOVER_KIND_TRANSFER,
    HandoverAppAction,
    HandoverGrantItem,
    HandoverTask,
    OnboardingTemplate,
    OnboardingTemplateRevisionItem,
    TransferPlan,
)

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

apply_transfer_diff_for_app = _grant_transfer.apply_transfer_diff_for_app
collect_kept_targets = _grant_transfer.collect_kept_targets
lock_and_validate_transfer_grant_versions = (
    _grant_transfer.lock_and_validate_transfer_grant_versions
)
merge_into_current_grant = _grant_transfer.merge_into_current_grant
transfer_selected_grants = _grant_transfer.transfer_selected_grants

diff_entries_by_key = _transfer_diff.diff_entries_by_key
diff_list = _transfer_diff.diff_list
entry_key = _transfer_diff.entry_key
frozen_add_item_from_diff_entry = _transfer_diff.frozen_add_item_from_diff_entry
grant_diff_entry = _transfer_diff.grant_diff_entry
grant_item_key = _transfer_diff.grant_item_key
later_expiry = _transfer_diff.later_expiry
optional_diff_int = _transfer_diff.optional_diff_int
optional_diff_text = _transfer_diff.optional_diff_text
required_diff_text = _transfer_diff.required_diff_text
revision_item_expiry = _transfer_diff.revision_item_expiry
template_diff_entry = _transfer_diff.template_diff_entry
template_item_expiry = _transfer_diff.template_item_expiry
template_item_key = _transfer_diff.template_item_key
template_term_replaces_snapshot = _transfer_diff.template_term_replaces_snapshot

_FrozenTransferAddItem = _transfer_diff.FrozenTransferAddItem
_transfer_diff_keys = _transfer_diff.transfer_diff_keys


def build_transfer_grant_diff(
    *,
    task: HandoverTask,
    template: OnboardingTemplate,
) -> TransferPlan:
    """转岗权限差异(§7 决策 9): 撤销不在新模板内的授权 + 补齐新模板, 确认时逐条可勾选。"""
    with transaction.atomic():
        task = HandoverTask.objects.select_for_update().get(pk=task.id)
        ensure_transfer_task_open(task)
        plan = TransferPlan.objects.select_for_update().get(task=task)
        if plan.confirmed_at is not None:
            raise HandoverConflictError(TRANSFER_CONFIRMATION_CONFLICT_MESSAGE)
        template = (
            OnboardingTemplate.objects.select_for_update(of=("self",))
            .select_related("current_revision")
            .get(pk=template.id)
        )
        template_revision = template.current_revision
        if template_revision is None:
            raise HandoverConflictError(TRANSFER_TEMPLATE_REVISION_MISSING_MESSAGE)
        current_entries = {
            grant_item_key(item): item for item in HandoverGrantItem.objects.filter(task=task)
        }
        template_entries = {
            template_item_key(item): item
            for item in OnboardingTemplateRevisionItem.objects.select_related(
                "app",
                "authorization_group",
                "permission",
            ).filter(revision=template_revision)
        }
        diff_keys = _transfer_diff_keys(current_entries, template_entries)
        plan.new_template = template
        plan.new_template_revision = template_revision
        plan.grant_diff = {
            "revoke": [grant_diff_entry(current_entries[key]) for key in diff_keys.revoke],
            "add": [template_diff_entry(template_entries[key]) for key in diff_keys.add],
            "keep": [grant_diff_entry(current_entries[key]) for key in diff_keys.keep],
        }
        plan.revision += 1
        plan.save(
            update_fields=[
                "new_template",
                "new_template_revision",
                "grant_diff",
                "revision",
                "updated_at",
            ],
        )
        return plan


def _confirmed_plan_or_conflict(
    plan: TransferPlan,
    *,
    canonical_revoke: list[str],
    canonical_add: list[str],
) -> TransferPlan:
    """已确认方案: 勾选完全一致时幂等返回, 否则判冲突。"""
    if plan.confirmed_revoke_keys == canonical_revoke and plan.confirmed_add_keys == canonical_add:
        return plan
    raise HandoverConflictError(TRANSFER_CONFIRMATION_CONFLICT_MESSAGE)


def _ensure_data_phase_settled(task: HandoverTask) -> None:
    """全部数据 action 收敛且无在途租约后才允许改权限(01 §5.5)。"""
    open_actions = list(HandoverAppAction.objects.filter(task=task))
    if any(a.status not in ACTION_FINISHED_STATUSES for a in open_actions):
        raise HandoverConflictError(HANDOVER_DATA_NOT_COMPLETED_MESSAGE)
    if any(action_execution_in_flight(a) for a in open_actions):
        raise HandoverConflictError(HANDOVER_DATA_NOT_COMPLETED_MESSAGE)


@dataclass(frozen=True, slots=True)
class _TransferSelection:
    revoke_set: set[str]
    add_set: set[str]
    frozen_add_items: dict[str, _FrozenTransferAddItem]
    apps: set[str]


def _resolve_transfer_selection(
    plan: TransferPlan,
    *,
    canonical_revoke: list[str],
    canonical_add: list[str],
) -> _TransferSelection:
    diff = plan.grant_diff
    add_entries = diff_entries_by_key(diff, "add")
    allowed_revoke = set(diff_entries_by_key(diff, "revoke"))
    allowed_add = set(add_entries)
    unknown = (set(canonical_revoke) - allowed_revoke) | (set(canonical_add) - allowed_add)
    if unknown:
        message = f"差异项不存在: {sorted(unknown)[0]}。"
        raise HandoverError(message)
    revoke_set = set(canonical_revoke)
    add_set = set(canonical_add)
    frozen_add_items = {key: frozen_add_item_from_diff_entry(add_entries[key]) for key in add_set}
    return _TransferSelection(
        revoke_set=revoke_set,
        add_set=add_set,
        frozen_add_items=frozen_add_items,
        apps={key.split(":", 1)[0] for key in revoke_set | add_set},
    )


def _apply_transfer_selection(
    task: HandoverTask,
    *,
    selection: _TransferSelection,
    actor_id: str,
) -> None:
    for app_key in sorted(selection.apps):
        apply_transfer_diff_for_app(
            subject=task.subject_user,
            app_key=app_key,
            revoke_keys={key for key in selection.revoke_set if key.startswith(f"{app_key}:")},
            add_items=[
                item
                for key, item in selection.frozen_add_items.items()
                if key in selection.add_set and key.startswith(f"{app_key}:")
            ],
            actor_id=actor_id,
        )


def confirm_transfer_grant_diff(
    *,
    task: HandoverTask,
    revoke_keys: list[str],
    add_keys: list[str],
    plan_revision: int,
    actor_id: str,
) -> TransferPlan:
    """按管理员勾选执行转岗权限调整(EasyAuth 内部完成, 无需钩子)。"""
    canonical_revoke = sorted(set(revoke_keys))
    canonical_add = sorted(set(add_keys))
    with transaction.atomic():
        task = (
            HandoverTask.objects.select_for_update().select_related("subject_user").get(pk=task.id)
        )
        if task.kind != HANDOVER_KIND_TRANSFER:
            raise HandoverConflictError(TRANSFER_TASK_REQUIRED_MESSAGE)
        plan = (
            TransferPlan.objects.select_for_update(of=("self",))
            .select_related("new_template", "new_template_revision")
            .get(task=task)
        )
        if plan.revision != plan_revision:
            raise HandoverConflictError(TRANSFER_PLAN_REVISION_CONFLICT_MESSAGE)
        if plan.confirmed_at is not None:
            return _confirmed_plan_or_conflict(
                plan,
                canonical_revoke=canonical_revoke,
                canonical_add=canonical_add,
            )
        ensure_task_open(task)
        _ensure_data_phase_settled(task)
        if plan.new_template is None or plan.new_template_revision is None:
            message = "请先选择新岗位模板并生成差异清单; 当前方案缺少绑定模板修订。"
            raise HandoverError(message)
        selection = _resolve_transfer_selection(
            plan,
            canonical_revoke=canonical_revoke,
            canonical_add=canonical_add,
        )
        lock_and_validate_transfer_grant_versions(task=task, app_keys=selection.apps)
        _apply_transfer_selection(task, selection=selection, actor_id=actor_id)
        return _finalize_transfer_plan(
            task,
            plan,
            canonical_revoke=canonical_revoke,
            canonical_add=canonical_add,
            actor_id=actor_id,
        )


def _finalize_transfer_plan(
    task: HandoverTask,
    plan: TransferPlan,
    *,
    canonical_revoke: list[str],
    canonical_add: list[str],
    actor_id: str,
) -> TransferPlan:
    plan.confirmed_at = timezone.now()
    plan.confirmed_revoke_keys = canonical_revoke
    plan.confirmed_add_keys = canonical_add
    plan.save(
        update_fields=[
            "confirmed_at",
            "confirmed_revoke_keys",
            "confirmed_add_keys",
            "updated_at",
        ],
    )
    record_task_event(
        task,
        action="handover_grant_diff_confirmed",
        actor_id=actor_id,
        extra={
            "revoked": cast("JsonValue", canonical_revoke),
            "added": cast("JsonValue", canonical_add),
        },
    )
    _ = refresh_task_status(task)
    return plan

"""第四轮交接分配与幂等审查项的回归测试。"""

from __future__ import annotations

import pytest

from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import App
from easyauth.lifecycle.assignments import OverrideEntry, patch_asset_type_defaults, put_overrides
from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
from easyauth.lifecycle.handover import _ensure_batch_plan_on_413
from easyauth.lifecycle.models import (
    ACTION_STATUS_PREVIEWED,
    BATCH_PLAN_STATUS_ABANDONED,
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_STATUS_PENDING,
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
    HandoverAppAction,
    HandoverAssetOverride,
    HandoverAssetType,
    HandoverBatchPlan,
    HandoverExecutionBatch,
    HandoverTask,
)
from easyauth.lifecycle.offboarding import _create_task_with_idempotency_constraint

pytestmark = pytest.mark.django_db


def _action() -> tuple[HandoverAppAction, HandoverAssetType, UserMirror]:
    subject = UserMirror.objects.create(
        authentik_user_id="r4-subject",
        status=USER_STATUS_ACTIVE,
    )
    receiver = UserMirror.objects.create(
        authentik_user_id="r4-receiver",
        status=USER_STATUS_ACTIVE,
    )
    app = App.objects.create(app_key="r4-app", name="第四轮应用")
    task = HandoverTask.objects.create(
        kind=HANDOVER_KIND_OFFBOARD,
        subject_user=subject,
    )
    action = HandoverAppAction.objects.create(
        task=task,
        app=app,
        status=ACTION_STATUS_PREVIEWED,
        generation=1,
        app_key_snapshot=app.app_key,
        app_name_snapshot=app.name,
    )
    asset_type = HandoverAssetType.objects.create(
        action=action,
        generation=1,
        type_key="customer",
        label_snapshot="客户",
        count=2,
        default_action="skip",
        releasable=True,
    )
    return action, asset_type, receiver


def test_pending_retry_batch_blocks_assignment_mutation_without_writes() -> None:
    action, asset_type, receiver = _action()
    _ = HandoverExecutionBatch.objects.create(
        action=action,
        action_snapshot_id=int(action.pk),
        generation=action.generation,
        batch_seq=1,
        snapshot_token="snapshot",
        request_payload={"assignments": [{"asset_type": "customer"}]},
        request_hash="a" * 64,
        status=BATCH_STATUS_PENDING,
    )

    with pytest.raises(HandoverConflictError, match="handover_execution_in_flight"):
        patch_asset_type_defaults(
            action,
            type_key="customer",
            default_action="transfer",
            default_to_user_id=receiver.authentik_user_id,
        )

    action.refresh_from_db()
    asset_type.refresh_from_db()
    assert action.confirm_version == 0
    assert asset_type.default_action == "skip"
    assert asset_type.default_to_user_id is None


def test_zero_progress_plan_is_atomically_replanned_after_assignment_change() -> None:
    action, asset_type, receiver = _action()
    old_plan = _ensure_batch_plan_on_413(action)

    _asset, confirm_version = patch_asset_type_defaults(
        action,
        type_key=asset_type.type_key,
        default_action="transfer",
        default_to_user_id=receiver.authentik_user_id,
    )

    old_plan.refresh_from_db()
    replacement = HandoverBatchPlan.objects.get(
        action=action,
        generation=action.generation,
        status=BATCH_PLAN_STATUS_ACTIVE,
    )
    assert old_plan.status == BATCH_PLAN_STATUS_ABANDONED
    assert replacement.pk != old_plan.pk
    assert replacement.assignment_hash != old_plan.assignment_hash
    assert confirm_version == 1


@pytest.mark.parametrize("mutation", ["default", "override"])
def test_non_transfer_assignment_rejects_receiver_before_database_constraint(
    mutation: str,
) -> None:
    action, asset_type, receiver = _action()

    with pytest.raises(HandoverError, match="receiver_not_allowed"):
        if mutation == "default":
            patch_asset_type_defaults(
                action,
                type_key=asset_type.type_key,
                default_action="skip",
                default_to_user_id=receiver.authentik_user_id,
            )
        else:
            put_overrides(
                action,
                type_key=asset_type.type_key,
                overrides_version=0,
                overrides=[
                    OverrideEntry(
                        asset_id="customer-1",
                        action="release",
                        to_user_id=receiver.authentik_user_id,
                    ),
                ],
            )

    action.refresh_from_db()
    assert action.confirm_version == 0
    assert action.overrides_version == 0
    assert not HandoverAssetOverride.objects.filter(asset_type=asset_type).exists()


def test_idempotency_unique_constraint_loser_returns_conflict_for_different_body() -> None:
    first = UserMirror.objects.create(
        authentik_user_id="r4-idem-first",
        status=USER_STATUS_ACTIVE,
    )
    second = UserMirror.objects.create(
        authentik_user_id="r4-idem-second",
        status=USER_STATUS_ACTIVE,
    )
    _ = HandoverTask.objects.create(
        kind=HANDOVER_KIND_REASSIGN,
        subject_user=first,
        created_by="manager-r4",
        creation_idempotency_key="same-key",
        creation_payload_sha256="1" * 64,
    )

    with pytest.raises(HandoverConflictError, match="idempotency_conflict"):
        _create_task_with_idempotency_constraint(
            kind=HANDOVER_KIND_REASSIGN,
            subject=second,
            created_by="manager-r4",
            reason="不同请求体",
            authority_source="manager_chain",
            creation_idempotency_key="same-key",
            creation_payload_sha256="2" * 64,
        )

    assert HandoverTask.objects.filter(
        created_by="manager-r4",
        creation_idempotency_key="same-key",
    ).count() == 1

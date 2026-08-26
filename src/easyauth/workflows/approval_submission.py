from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.integrations.dingtalk.api_client import DingTalkApiClient, DingTalkApiError
from easyauth.workflows.approval_events import record_instance_event
from easyauth.workflows.approval_state import (
    lock_or_create_approval_instance,
    mark_submission_error,
    mark_submitted,
    mark_submitting,
    submission_result_is_ambiguous,
)
from easyauth.workflows.approval_types import (
    ApprovalCreateError,
    ApprovalCreateRequest,
    ApprovalSubmission,
)
from easyauth.workflows.approval_validation import validated_approval_submission

if TYPE_CHECKING:
    from easyauth.workflows.models import ApprovalInstance


def create_approval_instance(request: ApprovalCreateRequest) -> tuple[ApprovalInstance, bool]:
    """发起一笔钉钉审批; 同 biz_key 幂等返回既有实例。返回 (instance, created)。"""
    submission = validated_approval_submission(request)
    instance, created, should_submit = lock_or_create_approval_instance(
        submission,
        biz_key=request.biz_key,
        retry_failed=request.retry_failed,
    )
    if not should_submit:
        return instance, False
    _submit_approval_instance(submission, instance=instance, actor_id=request.actor_id)
    return instance, created


def _submit_approval_instance(
    submission: ApprovalSubmission,
    *,
    instance: ApprovalInstance,
    actor_id: str,
) -> None:
    mark_submitting(instance)
    try:
        # 与 services.DingTalkApiClient 同为该类对象; tests 对
        # easyauth.workflows.services.DingTalkApiClient.from_settings 的 patch 落在 class 上,
        # 此处按调用时查找 from_settings, 缝仍有效。
        process_instance_id = DingTalkApiClient.from_settings().create_process_instance(
            process_code=submission.template.dingtalk_process_code,
            originator_userid=submission.originator.dingtalk_userid,
            form_components=submission.form_components,
        )
    except DingTalkApiError as error:
        ambiguous = submission_result_is_ambiguous(error)
        mark_submission_error(instance, error=error, ambiguous=ambiguous)
        record_instance_event(
            instance,
            action=(
                "approval_instance_submission_ambiguous"
                if ambiguous
                else "approval_instance_create_failed"
            ),
            actor_id=actor_id,
        )
        raise ApprovalCreateError(kind="dependency_unavailable", message=str(error)) from error

    _ = mark_submitted(instance, process_instance_id=process_instance_id)
    record_instance_event(instance, action="approval_instance_submitted", actor_id=actor_id)

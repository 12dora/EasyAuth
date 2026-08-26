from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from easyauth.applications.integration_settings import dingtalk_runtime_config
from easyauth.integrations.dingtalk.api_client import (
    DingTalkApiError,
    DingTalkApiRequestError,
    DingTalkApiUnavailableError,
    DingTalkNotConfiguredError,
)
from easyauth.workflows.approval_delivery import deliver_completion
from easyauth.workflows.approval_events import record_instance_event
from easyauth.workflows.approval_recovery import recover_stale_submission
from easyauth.workflows.approval_types import (
    IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE,
    INSTANCE_STATUS_CONFLICT_MESSAGE,
    RETRY_REQUIRED_MESSAGE,
    RETRY_STATE_CONFLICT_MESSAGE,
    SUBMISSION_AMBIGUOUS_MESSAGE,
    SUBMISSION_DEADLINE_GRACE_SECONDS,
    SUBMISSION_IN_PROGRESS_MESSAGE,
    ApprovalCallbackConflictError,
    ApprovalCreateError,
    ApprovalSubmission,
)
from easyauth.workflows.models import (
    APPROVAL_STATUS_CREATED,
    APPROVAL_STATUS_FAILED,
    APPROVAL_STATUS_SUBMITTED,
    APPROVAL_TERMINAL_STATUSES,
    CALLBACK_STATE_APPLIED,
    CALLBACK_STATE_CONFLICT,
    SUBMISSION_STATE_AMBIGUOUS,
    SUBMISSION_STATE_FAILED,
    SUBMISSION_STATE_PENDING,
    SUBMISSION_STATE_SUBMITTED,
    SUBMISSION_STATE_SUBMITTING,
    ApprovalInstance,
    PendingApprovalCallback,
)


def lock_or_create_approval_instance(
    submission: ApprovalSubmission,
    *,
    biz_key: str,
    retry_failed: bool,
) -> tuple[ApprovalInstance, bool, bool]:
    _recover_existing_approval_submission(submission, biz_key=biz_key)
    try:
        with transaction.atomic():
            instance = (
                ApprovalInstance.objects.select_for_update()
                .filter(
                    app=submission.app,
                    template=submission.template,
                    biz_key=biz_key,
                )
                .first()
            )
            if instance is None:
                instance = ApprovalInstance.objects.create(
                    app=submission.app,
                    template=submission.template,
                    biz_key=biz_key,
                    originator_user=submission.originator,
                    form_values=submission.normalized_form,
                    payload_hash=submission.payload_hash,
                )
                return instance, True, True
            should_submit = _prepare_existing_instance(
                instance,
                payload_hash=submission.payload_hash,
                retry_failed=retry_failed,
            )
            return instance, False, should_submit
    except IntegrityError:
        with transaction.atomic():
            winner = ApprovalInstance.objects.select_for_update().get(
                app=submission.app,
                template=submission.template,
                biz_key=biz_key,
            )
            should_submit = _prepare_existing_instance(
                winner,
                payload_hash=submission.payload_hash,
                retry_failed=retry_failed,
            )
            return winner, False, should_submit


def _recover_existing_approval_submission(
    submission: ApprovalSubmission,
    *,
    biz_key: str,
) -> None:
    existing = ApprovalInstance.objects.filter(
        app=submission.app,
        template=submission.template,
        biz_key=biz_key,
    ).first()
    if existing is not None:
        _ = recover_stale_submission(existing)


def _prepare_existing_instance(
    instance: ApprovalInstance,
    *,
    payload_hash: str,
    retry_failed: bool,
) -> bool:
    if instance.payload_hash != payload_hash:
        raise ApprovalCreateError(kind="conflict", message=IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE)
    if retry_failed:
        if instance.submission_state != SUBMISSION_STATE_FAILED:
            raise ApprovalCreateError(kind="conflict", message=RETRY_STATE_CONFLICT_MESSAGE)
        instance.status = APPROVAL_STATUS_CREATED
        instance.submission_state = SUBMISSION_STATE_PENDING
        instance.submission_deadline_at = None
        instance.last_error = ""
        instance.save(
            update_fields=[
                "status",
                "submission_state",
                "submission_deadline_at",
                "last_error",
                "updated_at",
            ],
        )
        return True
    if instance.submission_state == SUBMISSION_STATE_SUBMITTED:
        return False
    if instance.submission_state == SUBMISSION_STATE_FAILED:
        raise ApprovalCreateError(kind="conflict", message=RETRY_REQUIRED_MESSAGE)
    if instance.submission_state == SUBMISSION_STATE_AMBIGUOUS:
        raise ApprovalCreateError(kind="conflict", message=SUBMISSION_AMBIGUOUS_MESSAGE)
    raise ApprovalCreateError(kind="conflict", message=SUBMISSION_IN_PROGRESS_MESSAGE)


def mark_submitting(instance: ApprovalInstance) -> None:
    with transaction.atomic():
        locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
        if locked.submission_state != SUBMISSION_STATE_PENDING:
            raise ApprovalCreateError(kind="conflict", message=SUBMISSION_IN_PROGRESS_MESSAGE)
        locked.submission_state = SUBMISSION_STATE_SUBMITTING
        timeout_seconds = max(dingtalk_runtime_config().timeout_seconds, 1)
        locked.submission_deadline_at = timezone.now() + timedelta(
            seconds=timeout_seconds + SUBMISSION_DEADLINE_GRACE_SECONDS,
        )
        locked.save(
            update_fields=["submission_state", "submission_deadline_at", "updated_at"],
        )
    instance.submission_state = SUBMISSION_STATE_SUBMITTING
    instance.submission_deadline_at = locked.submission_deadline_at


def mark_submission_error(
    instance: ApprovalInstance,
    *,
    error: DingTalkApiError,
    ambiguous: bool,
) -> None:
    with transaction.atomic():
        locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
        locked.submission_state = (
            SUBMISSION_STATE_AMBIGUOUS if ambiguous else SUBMISSION_STATE_FAILED
        )
        locked.status = APPROVAL_STATUS_CREATED if ambiguous else APPROVAL_STATUS_FAILED
        locked.submission_deadline_at = None
        locked.last_error = str(error)
        locked.save(
            update_fields=[
                "submission_state",
                "status",
                "submission_deadline_at",
                "last_error",
                "updated_at",
            ],
        )
    instance.submission_state = locked.submission_state
    instance.status = locked.status
    instance.submission_deadline_at = None
    instance.last_error = locked.last_error


def submission_result_is_ambiguous(error: DingTalkApiError) -> bool:
    if isinstance(error, DingTalkNotConfiguredError):
        return False
    if isinstance(error, DingTalkApiUnavailableError):
        return True
    return isinstance(error, DingTalkApiRequestError) and error.status_code is None


def mark_submitted(instance: ApprovalInstance, *, process_instance_id: str) -> bool:
    try:
        with transaction.atomic():
            locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
            if locked.submission_state != SUBMISSION_STATE_SUBMITTING:
                raise ApprovalCreateError(kind="conflict", message=SUBMISSION_IN_PROGRESS_MESSAGE)
            locked.dingtalk_process_instance_id = process_instance_id
            locked.status = APPROVAL_STATUS_SUBMITTED
            locked.submission_state = SUBMISSION_STATE_SUBMITTED
            locked.submission_deadline_at = None
            locked.last_error = ""
            locked.save(
                update_fields=[
                    "dingtalk_process_instance_id",
                    "status",
                    "submission_state",
                    "submission_deadline_at",
                    "last_error",
                    "updated_at",
                ],
            )
            callback = (
                PendingApprovalCallback.objects.select_for_update()
                .filter(process_instance_id=process_instance_id)
                .first()
            )
            changed = False
            if callback is not None:
                changed, conflict = apply_callback_locked(locked, callback)
                if conflict is not None:
                    raise conflict
                if changed:
                    deliver_completion(locked)
    except IntegrityError as error:
        message = "钉钉返回了已关联其他审批实例的 process_instance_id。"
        mark_submission_error(
            instance,
            error=DingTalkApiRequestError(message),
            ambiguous=True,
        )
        raise ApprovalCreateError(kind="conflict", message=message) from error
    instance.dingtalk_process_instance_id = locked.dingtalk_process_instance_id
    instance.status = locked.status
    instance.submission_state = locked.submission_state
    instance.submission_deadline_at = locked.submission_deadline_at
    instance.last_error = locked.last_error
    instance.completed_at = locked.completed_at
    return changed


def apply_callback_locked(
    instance: ApprovalInstance,
    callback: PendingApprovalCallback,
) -> tuple[bool, ApprovalCallbackConflictError | None]:
    if instance.status == callback.status:
        if callback.state != CALLBACK_STATE_APPLIED:
            callback.state = CALLBACK_STATE_APPLIED
            callback.instance = instance
            callback.applied_at = instance.completed_at or timezone.now()
            callback.last_error = ""
            callback.save(
                update_fields=["state", "instance", "applied_at", "last_error", "updated_at"],
            )
        return False, None
    if instance.status in APPROVAL_TERMINAL_STATUSES:
        callback.state = CALLBACK_STATE_CONFLICT
        callback.instance = instance
        callback.last_error = INSTANCE_STATUS_CONFLICT_MESSAGE
        callback.applied_at = None
        callback.save(update_fields=["state", "instance", "last_error", "applied_at", "updated_at"])
        return False, ApprovalCallbackConflictError(
            instance_id=str(instance.id),
            status=instance.status,
        )
    instance.status = callback.status
    instance.completed_at = timezone.now()
    instance.save(update_fields=["status", "completed_at", "updated_at"])
    callback.state = CALLBACK_STATE_APPLIED
    callback.instance = instance
    callback.applied_at = instance.completed_at
    callback.last_error = ""
    callback.save(
        update_fields=["state", "instance", "applied_at", "last_error", "updated_at"],
    )
    record_instance_event(
        instance,
        action=f"approval_instance_{callback.status}",
        actor_id="dingtalk_callback",
    )
    return True, None

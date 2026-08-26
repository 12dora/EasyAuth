from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from easyauth.workflows.approval_types import SUBMISSION_AMBIGUOUS_MESSAGE
from easyauth.workflows.models import (
    SUBMISSION_STATE_AMBIGUOUS,
    SUBMISSION_STATE_SUBMITTING,
    ApprovalInstance,
)


def recover_stale_submission(instance: ApprovalInstance) -> ApprovalInstance:
    with transaction.atomic():
        locked = ApprovalInstance.objects.select_for_update().get(id=instance.id)
        _mark_stale_submission_ambiguous_locked(locked)
    if locked.submission_state != instance.submission_state:
        instance.submission_state = locked.submission_state
        instance.submission_deadline_at = locked.submission_deadline_at
        instance.last_error = locked.last_error
    return instance


def recover_stale_submissions(
    instances: tuple[ApprovalInstance, ...],
) -> tuple[ApprovalInstance, ...]:
    now = timezone.now()
    due_ids = tuple(
        instance.id
        for instance in instances
        if (
            instance.submission_state == SUBMISSION_STATE_SUBMITTING
            and instance.submission_deadline_at is not None
            and instance.submission_deadline_at <= now
        )
    )
    if not due_ids:
        return instances
    updated = ApprovalInstance.objects.filter(
        id__in=due_ids,
        submission_state=SUBMISSION_STATE_SUBMITTING,
        submission_deadline_at__lte=now,
    ).update(
        submission_state=SUBMISSION_STATE_AMBIGUOUS,
        submission_deadline_at=None,
        last_error=SUBMISSION_AMBIGUOUS_MESSAGE,
        updated_at=now,
    )
    if updated == 0:
        return instances
    for instance in instances:
        if instance.id in due_ids:
            instance.submission_state = SUBMISSION_STATE_AMBIGUOUS
            instance.submission_deadline_at = None
            instance.last_error = SUBMISSION_AMBIGUOUS_MESSAGE
            instance.updated_at = now
    return instances


def _mark_stale_submission_ambiguous_locked(instance: ApprovalInstance) -> None:
    if (
        instance.submission_state != SUBMISSION_STATE_SUBMITTING
        or instance.submission_deadline_at is None
        or instance.submission_deadline_at > timezone.now()
    ):
        return
    instance.submission_state = SUBMISSION_STATE_AMBIGUOUS
    instance.submission_deadline_at = None
    instance.last_error = SUBMISSION_AMBIGUOUS_MESSAGE
    instance.save(
        update_fields=[
            "submission_state",
            "submission_deadline_at",
            "last_error",
            "updated_at",
        ],
    )

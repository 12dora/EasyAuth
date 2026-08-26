from __future__ import annotations

from easyauth.integrations.dingtalk.api_client import DingTalkApiClient
from easyauth.workflows.approval_callbacks import apply_instance_callback
from easyauth.workflows.approval_delivery import completion_event_payload, deliver_completion
from easyauth.workflows.approval_recovery import recover_stale_submission, recover_stale_submissions
from easyauth.workflows.approval_submission import create_approval_instance
from easyauth.workflows.approval_types import (
    ApprovalCallbackConflictError,
    ApprovalCreateError,
    ApprovalCreateRequest,
    ApprovalInstanceNotFoundError,
)

__all__ = [
    "ApprovalCallbackConflictError",
    "ApprovalCreateError",
    "ApprovalCreateRequest",
    "ApprovalInstanceNotFoundError",
    "DingTalkApiClient",
    "apply_instance_callback",
    "completion_event_payload",
    "create_approval_instance",
    "deliver_completion",
    "recover_stale_submission",
    "recover_stale_submissions",
]

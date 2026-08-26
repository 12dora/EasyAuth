from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, override

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.accounts.models import UserMirror
    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue
    from easyauth.integrations.dingtalk.api_client import DingTalkFormComponent
    from easyauth.workflows.models import ApprovalTemplate

type ApprovalCreateErrorKind = Literal[
    "conflict",
    "dependency_unavailable",
    "originator_invalid",
    "template_not_found",
    "validation_error",
]

TEMPLATE_NOT_FOUND_MESSAGE: Final = "审批模板不存在或未启用。"
ORIGINATOR_INVALID_MESSAGE: Final = "发起人不存在、已停用或缺少钉钉绑定。"
INSTANCE_STATUS_CONFLICT_MESSAGE: Final = "回调状态与审批实例状态不匹配。"
INSTANCE_NOT_FOUND_MESSAGE: Final = "审批实例不存在。"
FORM_SCHEMA_INVALID_MESSAGE: Final = "审批模板 form_schema 或提交的 form 不符合契约。"
IDEMPOTENCY_PAYLOAD_CONFLICT_MESSAGE: Final = "同一 biz_key 已使用不同的发起人或表单载荷。"
RETRY_REQUIRED_MESSAGE: Final = "审批提交失败, 必须显式设置 retry=true 后重试。"
SUBMISSION_AMBIGUOUS_MESSAGE: Final = "钉钉是否已创建审批无法确认, 禁止盲目重试。"
SUBMISSION_IN_PROGRESS_MESSAGE: Final = "审批正在提交, 请勿重复发起。"
RETRY_STATE_CONFLICT_MESSAGE: Final = "只有明确失败的审批实例允许显式重试。"
SUBMISSION_DEADLINE_GRACE_SECONDS: Final = 5


@dataclass(frozen=True, slots=True)
class ApprovalCreateError(Exception):
    kind: ApprovalCreateErrorKind
    message: str

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ApprovalCallbackConflictError(Exception):
    instance_id: str
    status: str

    @override
    def __str__(self) -> str:
        return INSTANCE_STATUS_CONFLICT_MESSAGE


class ApprovalInstanceNotFoundError(LookupError):
    def __init__(self) -> None:
        super().__init__(INSTANCE_NOT_FOUND_MESSAGE)


@dataclass(frozen=True, slots=True)
class ApprovalCreateRequest:
    """发起审批的完整业务事实。"""

    app: App
    template_key: str
    originator_user_id: str
    form: Mapping[str, JsonValue]
    biz_key: str
    actor_id: str
    selected_template: ApprovalTemplate | None = None
    retry_failed: bool = False


@dataclass(frozen=True, slots=True)
class ApprovalSubmission:
    app: App
    template: ApprovalTemplate
    originator: UserMirror
    normalized_form: dict[str, JsonValue]
    form_components: tuple[DingTalkFormComponent, ...]
    payload_hash: str

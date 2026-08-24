"""定义生命周期领域共享的状态, 类型, 来源与租约常量。"""

from datetime import timedelta
from typing import Final

HANDOVER_KIND_OFFBOARD: Final = "offboard"
HANDOVER_KIND_TRANSFER: Final = "transfer"
HANDOVER_KIND_PRE_OFFBOARD: Final = "pre_offboard"
HANDOVER_KIND_REASSIGN: Final = "reassign"
HANDOVER_KIND_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (HANDOVER_KIND_OFFBOARD, "offboard"),
    (HANDOVER_KIND_TRANSFER, "transfer"),
    (HANDOVER_KIND_PRE_OFFBOARD, "pre_offboard"),
    (HANDOVER_KIND_REASSIGN, "reassign"),
)
HANDOVER_KIND_VALUES: Final[tuple[str, ...]] = (
    HANDOVER_KIND_OFFBOARD,
    HANDOVER_KIND_TRANSFER,
    HANDOVER_KIND_PRE_OFFBOARD,
    HANDOVER_KIND_REASSIGN,
)
# 会改动授权的 kind(整单层面); action 执行路径见 ACTION_GRANT_TRANSFER_KINDS。
GRANT_MUTATING_KINDS: Final[tuple[str, ...]] = (HANDOVER_KIND_OFFBOARD, HANDOVER_KIND_TRANSFER)
# action 执行路径是否调用 transfer_selected_grants: 只有 offboard。
ACTION_GRANT_TRANSFER_KINDS: Final[tuple[str, ...]] = (HANDOVER_KIND_OFFBOARD,)

ASSIGNEE_STATE_MANAGER: Final = "manager"
ASSIGNEE_STATE_SUBJECT: Final = "subject"
ASSIGNEE_STATE_SUPERUSER_POOL: Final = "superuser_pool"
ASSIGNEE_STATE_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ASSIGNEE_STATE_MANAGER, "manager"),
    (ASSIGNEE_STATE_SUBJECT, "subject"),
    (ASSIGNEE_STATE_SUPERUSER_POOL, "superuser_pool"),
)
ASSIGNEE_STATE_VALUES: Final[tuple[str, ...]] = (
    ASSIGNEE_STATE_MANAGER,
    ASSIGNEE_STATE_SUBJECT,
    ASSIGNEE_STATE_SUPERUSER_POOL,
)

HANDOVER_ESCALATION_DAYS: Final = 14
LEASE_TTL: Final = timedelta(minutes=5)
LEASE_RENEW_INTERVAL: Final = LEASE_TTL / 3

ONBOARDING_TEMPLATE_REVISION_IMMUTABLE_MESSAGE: Final = "OnboardingTemplateRevision is immutable."
ONBOARDING_TEMPLATE_REVISION_ITEM_IMMUTABLE_MESSAGE: Final = (
    "OnboardingTemplateRevisionItem is immutable."
)

TASK_STATUS_PENDING: Final = "pending"
TASK_STATUS_IN_PROGRESS: Final = "in_progress"
TASK_STATUS_COMPLETED: Final = "completed"
TASK_STATUS_CANCELLED: Final = "cancelled"
TASK_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (TASK_STATUS_PENDING, "pending"),
    (TASK_STATUS_IN_PROGRESS, "in_progress"),
    (TASK_STATUS_COMPLETED, "completed"),
    (TASK_STATUS_CANCELLED, "cancelled"),
)
TASK_STATUS_VALUES: Final[tuple[str, ...]] = (
    TASK_STATUS_PENDING,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_CANCELLED,
)
TASK_OPEN_STATUSES: Final[tuple[str, ...]] = (TASK_STATUS_PENDING, TASK_STATUS_IN_PROGRESS)

ACTION_STATUS_PENDING: Final = "pending"
ACTION_STATUS_PREVIEWED: Final = "previewed"
ACTION_STATUS_EXECUTING: Final = "executing"
ACTION_STATUS_ASYNC_PENDING: Final = "async_pending"
ACTION_STATUS_ASYNC_ATTENTION_REQUIRED: Final = "async_attention_required"
ACTION_STATUS_DONE: Final = "done"
ACTION_STATUS_FAILED: Final = "failed"
ACTION_STATUS_SKIPPED: Final = "skipped"
ACTION_STATUS_BLOCKED: Final = "blocked"
ACTION_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ACTION_STATUS_PENDING, "pending"),
    (ACTION_STATUS_PREVIEWED, "previewed"),
    (ACTION_STATUS_EXECUTING, "executing"),
    (ACTION_STATUS_ASYNC_PENDING, "async_pending"),
    (ACTION_STATUS_ASYNC_ATTENTION_REQUIRED, "async_attention_required"),
    (ACTION_STATUS_DONE, "done"),
    (ACTION_STATUS_FAILED, "failed"),
    (ACTION_STATUS_SKIPPED, "skipped"),
    (ACTION_STATUS_BLOCKED, "blocked"),
)
ACTION_STATUS_VALUES: Final[tuple[str, ...]] = (
    ACTION_STATUS_PENDING,
    ACTION_STATUS_PREVIEWED,
    ACTION_STATUS_EXECUTING,
    ACTION_STATUS_ASYNC_PENDING,
    ACTION_STATUS_ASYNC_ATTENTION_REQUIRED,
    ACTION_STATUS_DONE,
    ACTION_STATUS_FAILED,
    ACTION_STATUS_SKIPPED,
    ACTION_STATUS_BLOCKED,
)
ACTION_FINISHED_STATUSES: Final[tuple[str, ...]] = (ACTION_STATUS_DONE, ACTION_STATUS_SKIPPED)
# 初始态: 建单后尚未开始执行, 不把 task 推进到 in_progress。
ACTION_INITIAL_STATUSES: Final[tuple[str, ...]] = (
    ACTION_STATUS_PENDING,
    ACTION_STATUS_BLOCKED,
    ACTION_STATUS_SKIPPED,
)

ITEM_STATUS_PENDING: Final = "pending"
ITEM_STATUS_DONE: Final = "done"
ITEM_STATUS_SKIPPED: Final = "skipped"
ITEM_STATUS_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ITEM_STATUS_PENDING, "pending"),
    (ITEM_STATUS_DONE, "done"),
    (ITEM_STATUS_SKIPPED, "skipped"),
)
ITEM_STATUS_VALUES: Final[tuple[str, ...]] = (
    ITEM_STATUS_PENDING,
    ITEM_STATUS_DONE,
    ITEM_STATUS_SKIPPED,
)

TEAM_ITEM_ACTION_PENDING: Final = "pending"
TEAM_ITEM_ACTION_ASSIGN_LEADER: Final = "assign_leader"
TEAM_ITEM_ACTION_DEACTIVATE: Final = "deactivate"
TEAM_ITEM_ACTION_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (TEAM_ITEM_ACTION_PENDING, "pending"),
    (TEAM_ITEM_ACTION_ASSIGN_LEADER, "assign_leader"),
    (TEAM_ITEM_ACTION_DEACTIVATE, "deactivate"),
)
TEAM_ITEM_ACTION_VALUES: Final[tuple[str, ...]] = (
    TEAM_ITEM_ACTION_PENDING,
    TEAM_ITEM_ACTION_ASSIGN_LEADER,
    TEAM_ITEM_ACTION_DEACTIVATE,
)

ASSET_ACTION_TRANSFER: Final = "transfer"
ASSET_ACTION_RELEASE: Final = "release"
ASSET_ACTION_SKIP: Final = "skip"
ASSET_ACTION_CHOICES: Final[tuple[tuple[str, str], ...]] = (
    (ASSET_ACTION_TRANSFER, "transfer"),
    (ASSET_ACTION_RELEASE, "release"),
    (ASSET_ACTION_SKIP, "skip"),
)
ASSET_ACTION_VALUES: Final[tuple[str, ...]] = (
    ASSET_ACTION_TRANSFER,
    ASSET_ACTION_RELEASE,
    ASSET_ACTION_SKIP,
)

BATCH_STATUS_PENDING: Final = "pending"
BATCH_STATUS_EXECUTING: Final = "executing"
BATCH_STATUS_ASYNC_PENDING: Final = "async_pending"
BATCH_STATUS_DATA_COMPLETED: Final = "data_completed"
BATCH_STATUS_DONE: Final = "done"
BATCH_STATUS_FAILED: Final = "failed"
BATCH_STATUS_VALUES: Final[tuple[str, ...]] = (
    BATCH_STATUS_PENDING,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_ASYNC_PENDING,
    BATCH_STATUS_DATA_COMPLETED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_FAILED,
)
# §5.5.1 skip/cancel: 仅真正在途; pending(429 重排队)不算 in-flight。
# 改分配端点另用 ASSIGNMENT_MUTATION_IN_FLIGHT_STATUSES(含 pending)。
BATCH_IN_FLIGHT_STATUSES: Final[tuple[str, ...]] = (
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_ASYNC_PENDING,
)
ASSIGNMENT_MUTATION_IN_FLIGHT_STATUSES: Final[tuple[str, ...]] = (
    BATCH_STATUS_PENDING,
    BATCH_STATUS_EXECUTING,
    BATCH_STATUS_ASYNC_PENDING,
)

DELIVERY_OUTCOME_SENT: Final = "sent"
DELIVERY_OUTCOME_SUCCEEDED: Final = "succeeded"
DELIVERY_OUTCOME_FAILED: Final = "failed"
DELIVERY_OUTCOME_ASYNC_ACCEPTED: Final = "async_accepted"
DELIVERY_OUTCOME_SUPERSEDED: Final = "superseded"
DELIVERY_OUTCOME_VALUES: Final[tuple[str, ...]] = (
    DELIVERY_OUTCOME_SENT,
    DELIVERY_OUTCOME_SUCCEEDED,
    DELIVERY_OUTCOME_FAILED,
    DELIVERY_OUTCOME_ASYNC_ACCEPTED,
    DELIVERY_OUTCOME_SUPERSEDED,
)

BATCH_PLAN_STATUS_ACTIVE: Final = "active"
BATCH_PLAN_STATUS_ABANDONED: Final = "abandoned"
BATCH_PLAN_STATUS_DONE: Final = "done"
BATCH_PLAN_STATUS_VALUES: Final[tuple[str, ...]] = (
    BATCH_PLAN_STATUS_ACTIVE,
    BATCH_PLAN_STATUS_ABANDONED,
    BATCH_PLAN_STATUS_DONE,
)

BLOCKED_REASON_CAPABILITY_UNDECLARED: Final = "capability_undeclared"
BLOCKED_REASON_DESCRIPTOR_UNREACHABLE: Final = "descriptor_unreachable"

AUTHORITY_SOURCE_MANAGER_CHAIN: Final = "manager_chain"
AUTHORITY_SOURCE_SUPERUSER: Final = "superuser"
AUTHORITY_SOURCE_SUBJECT: Final = "subject"
AUTHORITY_SOURCE_VALUES: Final[tuple[str, ...]] = (
    AUTHORITY_SOURCE_MANAGER_CHAIN,
    AUTHORITY_SOURCE_SUPERUSER,
    AUTHORITY_SOURCE_SUBJECT,
)

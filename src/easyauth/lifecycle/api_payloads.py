"""交接单/action 的 §6.2 响应形状。门户与控制台共享, 不含 HTTP 身份逻辑。"""

from easyauth.lifecycle.api_payloads_actions import (
    SURFACE_CONSOLE,
    SURFACE_PORTAL,
    action_item,
    aggregated_summary,
    allowed_actions_for,
    asset_type_item,
    batch_progress,
    team_item,
)
from easyauth.lifecycle.api_payloads_people import handover_list_people, user_ref
from easyauth.lifecycle.api_payloads_tasks import (
    console_task_list_item,
    escalation_payload,
    task_detail,
    task_list_item,
)

__all__ = [
    "SURFACE_CONSOLE",
    "SURFACE_PORTAL",
    "action_item",
    "aggregated_summary",
    "allowed_actions_for",
    "asset_type_item",
    "batch_progress",
    "console_task_list_item",
    "escalation_payload",
    "handover_list_people",
    "task_detail",
    "task_list_item",
    "team_item",
    "user_ref",
]

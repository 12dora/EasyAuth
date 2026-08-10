"""交接 HTTP 细错误码(01 §6.1 / §6.3)。细码一律落 details.reason。"""

from __future__ import annotations

from http import HTTPStatus
from typing import Final

from django.http import JsonResponse

from easyauth.api.errors import ErrorCode, JsonValue
from easyauth.api.responses import error_response

# HTTPStatus already imported for reason table + HookCallError mapping

# reason → (HTTP, ErrorCode, 默认中文文案)
_REASON_TABLE: Final[dict[str, tuple[int, ErrorCode, str]]] = {
    "out_of_managed_scope": (
        HTTPStatus.FORBIDDEN,
        ErrorCode.PERMISSION_DENIED,
        "该员工不在你的管辖范围内。",
    ),
    "open_task_exists": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "该人员已有进行中的交接单。",
    ),
    "handover_execution_in_flight": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "该应用交接正在执行中，请稍后再试。",
    ),
    "payload_too_large": (
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        ErrorCode.VALIDATION_ERROR,
        "本批载荷过大，请按分批进度重新预演后执行下一批。",
    ),
    "snapshot_stale": (
        HTTPStatus.PRECONDITION_FAILED,
        ErrorCode.CONFLICT,
        "清单已变化，请重新预演。",
    ),
    "downstream_locked": (
        HTTPStatus.LOCKED,
        ErrorCode.CONFLICT,
        "下游对象被临时锁定，请稍后重试。",
    ),
    "action_not_retryable": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "当前状态不可重试。",
    ),
    "reason_required": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "理由至少 10 个字符。",
    ),
    "receiver_not_active": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "接收人未激活。",
    ),
    "receiver_is_subject": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "接收人不能是当事人本人。",
    ),
    "grant_receiver_not_allowed": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "仅 offboard 允许设置 grant_receiver。",
    ),
    "receiver_required": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "转移动作必须指定接收人。",
    ),
    "asset_type_not_releasable": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "该资产类型不支持释放。",
    ),
    "duplicate_assignment": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "分配存在重复项。",
    ),
    "detail_not_supported": (
        HTTPStatus.BAD_REQUEST,
        ErrorCode.VALIDATION_ERROR,
        "该资产类型不支持明细。",
    ),
    "directory_unavailable": (
        HTTPStatus.SERVICE_UNAVAILABLE,
        ErrorCode.DEPENDENCY_UNAVAILABLE,
        "组织目录暂不可用，请稍后重试。",
    ),
    "purpose_required": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "purpose 参数必填。",
    ),
    "action_blocked": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "该应用未接入交接能力，无法预演或执行。",
    ),
    "confirm_version_stale": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "确认版本已过期，请刷新后重新确认。",
    ),
    "overrides_version_stale": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "覆盖版本已过期，请重新加载后再保存。",
    ),
    "batch_plan_in_progress": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "分批计划进行中，不能修改分配。",
    ),
    "idempotency_conflict": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "同一幂等键对应不同请求体。",
    ),
    "idempotency_key_required": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "必须提供 Idempotency-Key 头。",
    ),
    "items_page_out_of_range": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "page 参数越界。",
    ),
    "items_query_too_long": (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        ErrorCode.SEMANTIC_VALIDATION_ERROR,
        "查询关键字过长。",
    ),
    "rate_limited": (
        HTTPStatus.TOO_MANY_REQUESTS,
        ErrorCode.THROTTLED,
        "请求过于频繁，请稍后重试。",
    ),
    "already_deferred": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "本层级已顺延过一次。",
    ),
    "already_resolved": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "该待办已解决。",
    ),
    "local_admin_cannot_claim": (
        HTTPStatus.FORBIDDEN,
        ErrorCode.PERMISSION_DENIED,
        "本地管理员不能认领交接单。",
    ),
    "action_not_operable": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "当前状态不可执行该操作。",
    ),
    "summary_conservation_failed": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "下游 summary 不守恒，已判失败。",
    ),
    "task_kind_conflict": (
        HTTPStatus.CONFLICT,
        ErrorCode.CONFLICT,
        "该人员已有其他类型的进行中交接单。",
    ),
}


def reason_error(
    reason: str,
    message: str | None = None,
    *,
    details: dict[str, JsonValue] | None = None,
) -> JsonResponse:
    entry = _REASON_TABLE.get(reason)
    if entry is None:
        return error_response(
            ErrorCode.VALIDATION_ERROR,
            message or reason,
            {"reason": reason, **(details or {})},
            status=HTTPStatus.BAD_REQUEST,
        )
    status, code, default_message = entry
    payload_details: dict[str, JsonValue] = {"reason": reason}
    if details:
        payload_details.update(details)
    return error_response(
        code,
        message or default_message,
        payload_details,
        status=status,
    )


def map_handover_exception(
    error: BaseException,
    *,
    details: dict[str, JsonValue] | None = None,
) -> JsonResponse | None:
    """将 domain 异常映射为 §6.1 响应; 无法识别时返回 None。

    ``details`` 会并入响应 details(例如 413 的 ``batch_progress``)。
    """
    from easyauth.lifecycle.errors import HandoverConflictError, HandoverError
    from easyauth.lifecycle.lease import HANDOVER_EXECUTION_IN_FLIGHT
    from easyauth.webhooks.hooks import HookCallError

    if isinstance(error, HookCallError):
        # 按 status_code 映射, 不用字符串子串(items / execute / preview 共用)
        status = error.status_code
        if status == HTTPStatus.PRECONDITION_FAILED:  # 412
            return reason_error("snapshot_stale", details=details)
        if status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE:  # 413
            return reason_error("payload_too_large", details=details)
        if status == HTTPStatus.LOCKED:  # 423
            return reason_error("downstream_locked", details=details)
        if status == HTTPStatus.TOO_MANY_REQUESTS:  # 429
            return reason_error("rate_limited", details=details)
        return None

    text = str(error).strip()
    if isinstance(error, HandoverConflictError):
        if text == HANDOVER_EXECUTION_IN_FLIGHT or "in_flight" in text:
            return reason_error("handover_execution_in_flight", details=details)
        if text in _REASON_TABLE:
            return reason_error(text, details=details)
        # 兼容既有中文冲突消息
        from easyauth.lifecycle.core import TASK_KIND_CONFLICT_MESSAGE

        if text == TASK_KIND_CONFLICT_MESSAGE:
            return reason_error("task_kind_conflict", text, details=details)
        return reason_error("action_not_operable", text, details=details)
    if isinstance(error, HandoverError):
        if text in _REASON_TABLE:
            return reason_error(text, details=details)
        # 中文消息回落: 下游 HTTP 提示
        if "412" in text:
            return reason_error("snapshot_stale", details=details)
        if "413" in text:
            return reason_error("payload_too_large", details=details)
        if "423" in text:
            return reason_error("downstream_locked", details=details)
        return None
    return None

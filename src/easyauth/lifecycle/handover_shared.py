"""交接流程共享常量、类型、锁查询与错误投影工具。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast

from easyauth.lifecycle.error_projection import project_handover_error
from easyauth.lifecycle.errors import HandoverError
from easyauth.lifecycle.models import (
    HandoverAppAction,
    HandoverBatchPlan,
    HandoverExecutionBatch,
    HandoverTask,
)
from easyauth.webhooks.models import AppWebhookConfig

if TYPE_CHECKING:
    from easyauth.applications.models import App
    from easyauth.applications.ops_models import JsonValue
    from easyauth.lifecycle.lease import LeaseHandle


class MutationGuard(Protocol):
    def __call__(self, action: HandoverAppAction) -> None: ...


logger = logging.getLogger(__name__)


TASK_ID_PATTERN: Final = re.compile(r"\A[0-9]+:[0-9]+\Z")


TASK_ID_MAX_LENGTH: Final = 64


RESPONSE_SUMMARY_KEY_LENGTH_LIMIT: Final = 64


ITEMS_PAGE_MAX: Final = 100_000


ITEMS_PAGE_SIZE_MAX: Final = 200


ITEMS_QUERY_MAX_BYTES: Final = 128


ITEMS_RATE_LIMIT_WINDOW_SECONDS: Final = 60


ITEMS_RATE_LIMIT_MAX: Final = 120


PAYLOAD_SOFT_LIMIT_BYTES: Final = 200 * 1024


SNAPSHOT_TOKEN_MAX_LEN: Final = 128


RESPONSE_PAYLOAD_DIGEST_MAX: Final = 512


SKIP_REASON_CAPABILITY_NONE: Final = "运营已声明本应用无用户级数据"


DECLARED_WITHOUT_URL_MESSAGE: Final = "declared 能力与 webhook 配置不一致"


POLICY_REMOVED_MESSAGE: Final = (
    "policy / release_to_pool 已移除; 权限接收人请用 grant_receiver, 数据接收人请用资产级分配。"
)


UNSHARDABLE_BATCH_MESSAGE: Final = "单独指定的条目过多, 请减少逐条指定后重新预演"


RATE_LIMITED_MESSAGE: Final = "rate_limited"


RATE_LIMITED_EXECUTE_RETRY_TASK: Final = "easyauth.lifecycle.retry_rate_limited_execute"


DEFAULT_RETRY_AFTER_SECONDS: Final = 60


ITEMS_RATE_LIMIT_NAMESPACE: Final = "handover-items"


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    action_id: int
    preview_generation: int
    generation: int
    app: App
    hook_url: str
    payload: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class AsyncPollClaim:
    """已 claim 到轮询者名下的租约上下文, 供发网后的三条回写路径复用。"""

    batch: HandoverExecutionBatch
    handle: LeaseHandle


@dataclass(frozen=True, slots=True)
class DataPhaseAudit:
    """收尾审计三元组; actor_id 与 extra 同时给出才落审计事件。"""

    actor_id: str | None
    actor_type: str
    extra: dict[str, JsonValue] | None


@dataclass(frozen=True, slots=True)
class DataPhaseGate:
    """事务 A 的出口: 守恒失败原因 / 非最终批已就地收尾 / 是否还要转授权。"""

    conservation_fail: str | None = None
    settled_non_final: bool = False
    needs_grant: bool = False


@dataclass(frozen=True, slots=True)
class GrantOnlyRetryOutcome:
    """纯授权重试的事务内结局; 失败态已提交, 由调用方在 atomic 外 raise。"""

    done_id: int | None = None
    error: Exception | None = None


@dataclass(frozen=True, slots=True)
class OutboundExecution:
    """事务内备好、事务外才发的一次 execute 投递。"""

    action_id: int
    batch_id: int
    delivery_id: int
    handle: LeaseHandle
    app: App
    url: str
    body: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ExecuteRequestBody:
    """一次执行请求的 canonical body 及其在批计划中的位置。"""

    payload: dict[str, JsonValue]
    request_hash: str
    is_final: bool
    plan: HandoverBatchPlan | None
    plan_batch_no: int | None


# ---------------------------------------------------------------------------
# preview 内部
# ---------------------------------------------------------------------------


def locked_action(action_id: int) -> HandoverAppAction:
    # of=("self",): PG 禁止对 nullable outer join 侧 FOR UPDATE(grant_receiver 可空)。
    return (
        HandoverAppAction.objects.select_for_update(of=("self",))
        .select_related(
            "app",
            "task",
            "task__subject_user",
            "grant_receiver",
        )
        .get(pk=action_id)
    )


def locked_action_after_task(action_id: int) -> HandoverAppAction:
    """§2.2 锁序 task → action: 先锁 task 再锁 action。"""
    task_id = (
        HandoverAppAction.objects.filter(pk=action_id).values_list("task_id", flat=True).first()
    )
    if task_id is None:
        raise HandoverAppAction.DoesNotExist
    _ = HandoverTask.objects.select_for_update().get(pk=task_id)
    return locked_action(action_id)


def task_id(action: HandoverAppAction) -> str:
    value = f"{action.task_id}:{action.app_id}"
    if not TASK_ID_PATTERN.fullmatch(value) or len(value) > TASK_ID_MAX_LENGTH:
        message = f"非法 task_id: {value!r}"
        raise HandoverError(message)
    return value


def handover_hook_url(app: App) -> str:
    config = AppWebhookConfig.objects.filter(app=app, enabled=True).first()
    if config is None:
        return ""
    return config.handover_url


def redact_response_payload(payload: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    """00 §10.6: 只存摘要 + SHA-256, 不存未限长原文。"""
    if not payload:
        return {}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    summary: dict[str, JsonValue] = {"sha256": digest, "byte_length": len(raw.encode("utf-8"))}
    if "summary" in payload and isinstance(payload["summary"], dict):
        summary["summary"] = cast("JsonValue", _safe_response_summary(payload["summary"]))
    return summary


def _safe_response_summary(payload_summary: dict[str, JsonValue]) -> dict[str, JsonValue]:
    # 00 §10.5 v2: summary 为 {type_key: {transferred, released, skipped, merged, failed}}
    # 五元组计数非敏感, 必须保留; 旧标量字段也兼容。
    counter_fields = ("transferred", "released", "skipped", "merged", "failed")
    safe: dict[str, JsonValue] = {}
    for key, value in payload_summary.items():
        if not isinstance(key, str) or len(key) >= RESPONSE_SUMMARY_KEY_LENGTH_LIMIT:
            continue
        if isinstance(value, int | float | str | bool):
            safe[key] = value
            continue
        if not isinstance(value, dict):
            continue
        row: dict[str, JsonValue] = {}
        for field in counter_fields:
            raw = value.get(field, 0)
            if isinstance(raw, int | float):
                row[field] = int(raw)
        if row:
            safe[key] = row
    return safe


def error_response_evidence(
    payload: dict[str, JsonValue] | None,
    *,
    raw_body: str,
) -> dict[str, JsonValue]:
    if raw_body:
        evidence_bytes = raw_body.encode("utf-8")
    elif payload is not None:
        evidence_bytes = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    else:
        return {}
    projection = project_handover_error(
        error="downstream_error",
        payload=payload,
        raw_body=raw_body,
    )
    return {
        "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
        "byte_length": len(evidence_bytes),
        "error_summary": projection.public,
        "raw_projection": projection.raw,
    }


def redact_error_text(text: str) -> str:
    return project_handover_error(error=text).public


@dataclass(frozen=True, slots=True)
class ActionErrorContext:
    status_code: int | None = None
    payload: dict[str, JsonValue] | None = None
    raw_body: str = ""
    stable_message: str | None = None


def set_action_error(
    action: HandoverAppAction,
    error: object,
    context: ActionErrorContext | None = None,
) -> None:
    if context is None:
        context = ActionErrorContext()
    projection = project_handover_error(
        error=error,
        status_code=context.status_code,
        payload=context.payload,
        raw_body=context.raw_body,
        stable_message=context.stable_message,
    )
    action.last_error = projection.public
    action.last_error_raw = projection.raw

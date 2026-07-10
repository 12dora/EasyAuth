from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
)
from easyauth.integrations.authentik.directory_refresh import refresh_dingtalk_directory
from easyauth.integrations.models import (
    STREAM_EVENT_STATUS_FAILED,
    STREAM_EVENT_STATUS_PROCESSED,
    STREAM_EVENT_STATUS_RECEIVED,
    STREAM_EVENT_STATUS_SKIPPED,
    DingTalkStreamEvent,
)
from easyauth.outbox.services import enqueue_task
from easyauth.workflows.models import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_CANCELED,
    APPROVAL_STATUS_REJECTED,
)
from easyauth.workflows.services import (
    ApprovalCallbackConflictError,
    ApprovalInstanceNotFoundError,
    apply_instance_callback,
)

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

PROCESS_STREAM_EVENT_TASK_NAME: Final = "easyauth.dingtalk_stream.process_event"
DIRECTORY_REFRESH_TASK_NAME: Final = "easyauth.dingtalk_stream.refresh_directory"

# 通讯录人员/部门变更事件: 都收敛为同一个动作——立即刷新钉钉目录镜像。
# 入职(user_add_org)不会创建任何账号(账号只在员工首次 OAuth 登录 Authentik 时产生),
# 一线员工的入离职因此只体现为目录镜像与主管链(MANAGED_USERS)的更新;
# 离职(user_leave_org)经由刷新后的目录同步管道触发撤权/交接单/Authentik 禁号。
DIRECTORY_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "user_add_org",
        "user_modify_org",
        "user_leave_org",
        "user_active_org",
        "org_dept_create",
        "org_dept_modify",
        "org_dept_remove",
    },
)
BPMS_INSTANCE_CHANGE_EVENT_TYPE: Final = "bpms_instance_change"

# 已订阅、需要接住但当前没有本地消费方的事件: 完整落库(收件箱即处置结果),
# 与"未知类型"区分开——后者说明订阅面和处理面不一致, 值得排查。
# 角色(label)与企业信息不进目录镜像, 不触发目录刷新;
# bpms_task_change 是审批节点级事件, 实例级状态仍以 bpms_instance_change 为准。
RECORD_ONLY_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "org_change",  # 企业信息发生变更
        "label_user_change",  # 员工角色信息发生变更
        "label_conf_add",  # 增加角色或角色组
        "label_conf_del",  # 删除角色或角色组
        "bpms_task_change",  # 审批任务开始/结束/转交(节点级)
    },
)

# 事件风暴合并——窗口内的多个目录事件只排一次刷新任务; 刷新任务开始执行时先清除
# 标记, 之后到达的事件会再次排队, 保证任何事件都被其后的一次完整同步覆盖。
REFRESH_PENDING_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-pending:{corp_id}"
REFRESH_COALESCE_SECONDS: Final = 5
# pending 标记必须有限期: 若刷新任务在执行前丢失(broker 故障), 标记过期后事件恢复排队。
REFRESH_PENDING_TTL_SECONDS: Final = 600

DIRECTORY_EVENT_MISSING_CORP_MESSAGE: Final = "钉钉目录事件缺少 corp_id。"
BPMS_EVENT_MISSING_INSTANCE_MESSAGE: Final = "钉钉审批事件缺少 processInstanceId。"
BPMS_EVENT_UNSUPPORTED_CHANGE_MESSAGE: Final = "钉钉审批事件状态组合无法识别。"

SKIP_REASON_UNHANDLED_EVENT_TYPE: Final = "unhandled_event_type"
SKIP_REASON_RECORDED_NO_CONSUMER: Final = "recorded_no_consumer"
SKIP_REASON_INSTANCE_NOT_FOUND: Final = "approval_instance_not_found"
SKIP_REASON_INSTANCE_STARTED: Final = "approval_instance_started"

# type=start 无 result; finish 才携带 agree/refuse; terminate 表示发起人撤销。
_BPMS_CHANGE_TO_STATUS: Final[dict[tuple[str, str], str]] = {
    ("finish", "agree"): APPROVAL_STATUS_APPROVED,
    ("finish", "refuse"): APPROVAL_STATUS_REJECTED,
    ("terminate", ""): APPROVAL_STATUS_CANCELED,
}


class StreamEventContractError(Exception):
    """事件载荷违反钉钉数据契约, 无法处理且重试无意义。"""


@dataclass(frozen=True, slots=True)
class StreamEventOutcome:
    status: str
    result: dict[str, JsonValue] = field(default_factory=dict)


def refresh_pending_cache_key(corp_id: str) -> str:
    return REFRESH_PENDING_CACHE_KEY_TEMPLATE.format(corp_id=corp_id)


def request_directory_refresh(corp_id: str, *, source_event_id: str) -> bool:
    """请求一次防抖合并的目录刷新; 返回是否真正排队了新任务。"""
    if not cache.add(refresh_pending_cache_key(corp_id), "1", timeout=REFRESH_PENDING_TTL_SECONDS):
        return False
    _ = enqueue_task(
        event_key=f"dingtalk-directory-refresh:{corp_id}:{source_event_id}",
        task_name=DIRECTORY_REFRESH_TASK_NAME,
        args=[corp_id],
        countdown=REFRESH_COALESCE_SECONDS,
    )
    return True


@shared_task(
    name=DIRECTORY_REFRESH_TASK_NAME,
    autoretry_for=(AuthentikDirectoryError,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def refresh_dingtalk_directory_task(corp_id: str) -> dict[str, int]:
    # 先清除 pending 标记再刷新: 此后到达的事件会重新排队, 不会被本轮已经开始的
    # Authentik 拉取错过。
    _ = cache.delete(refresh_pending_cache_key(corp_id))
    client = AuthentikDirectoryClient.from_settings()
    result = refresh_dingtalk_directory(client, corp_id)
    return {
        "department_count": result.department_count,
        "user_count": result.user_count,
        "org_context_count": result.org_context_count,
        "status_applied_count": result.status_applied_count,
        "departed_count": result.departed_count,
        "revoked_count": result.revoked_count,
        "pruned_user_count": result.pruned_user_count,
    }


@shared_task(name=PROCESS_STREAM_EVENT_TASK_NAME, acks_late=True)
def process_dingtalk_stream_event_task(event_pk: int) -> str:
    dispatch_error: StreamEventContractError | ApprovalCallbackConflictError | None = None
    with transaction.atomic():
        event = DingTalkStreamEvent.objects.select_for_update().get(pk=event_pk)
        if event.status != STREAM_EVENT_STATUS_RECEIVED:
            # 重复投递/重放的幂等出口: 已处理事件不再产生任何副作用。
            return event.status
        try:
            outcome = dispatch_stream_event(event)
        except (StreamEventContractError, ApprovalCallbackConflictError) as error:
            _finalize_event(event, status=STREAM_EVENT_STATUS_FAILED, error=str(error))
            dispatch_error = error
        else:
            _finalize_event(event, status=outcome.status, result=outcome.result)
    if dispatch_error is not None:
        raise dispatch_error
    return event.status


def dispatch_stream_event(event: DingTalkStreamEvent) -> StreamEventOutcome:
    if event.event_type in DIRECTORY_EVENT_TYPES:
        return _handle_directory_event(event)
    if event.event_type == BPMS_INSTANCE_CHANGE_EVENT_TYPE:
        return _handle_bpms_instance_change(event)
    if event.event_type in RECORD_ONLY_EVENT_TYPES:
        return StreamEventOutcome(
            status=STREAM_EVENT_STATUS_SKIPPED,
            result={"reason": SKIP_REASON_RECORDED_NO_CONSUMER},
        )
    # 未纳入处理的事件类型保留在收件箱(status=skipped), 是后续扩展(智能人事、
    # 考勤等)的观测依据, 不算失败。
    return StreamEventOutcome(
        status=STREAM_EVENT_STATUS_SKIPPED,
        result={"reason": SKIP_REASON_UNHANDLED_EVENT_TYPE},
    )


def _handle_directory_event(event: DingTalkStreamEvent) -> StreamEventOutcome:
    corp_id = (
        event.corp_id
        or _data_string(event.data, "corpId")
        or _data_string(
            event.data,
            "CorpId",
        )
    )
    if not corp_id:
        raise StreamEventContractError(DIRECTORY_EVENT_MISSING_CORP_MESSAGE)
    refresh_queued = request_directory_refresh(corp_id, source_event_id=event.event_id)
    result: dict[str, JsonValue] = {
        "corp_id": corp_id,
        "refresh_queued": refresh_queued,
    }
    user_ids = _data_string_list(event.data, "userId") or _data_string_list(event.data, "UserId")
    if user_ids:
        result["user_ids"] = list(user_ids)
    return StreamEventOutcome(status=STREAM_EVENT_STATUS_PROCESSED, result=result)


def _handle_bpms_instance_change(event: DingTalkStreamEvent) -> StreamEventOutcome:
    process_instance_id = _data_string(event.data, "processInstanceId")
    if not process_instance_id:
        raise StreamEventContractError(BPMS_EVENT_MISSING_INSTANCE_MESSAGE)
    change_type = _data_string(event.data, "type")
    change_result = _data_string(event.data, "result")
    if change_type == "start":
        # 实例创建事件: 实例由 EasyAuth 自己发起, 提交状态已在创建时落库。
        return StreamEventOutcome(
            status=STREAM_EVENT_STATUS_SKIPPED,
            result={
                "reason": SKIP_REASON_INSTANCE_STARTED,
                "process_instance_id": process_instance_id,
            },
        )
    normalized_result = change_result if change_type == "finish" else ""
    status = _BPMS_CHANGE_TO_STATUS.get((change_type, normalized_result))
    if status is None:
        message = (
            f"{BPMS_EVENT_UNSUPPORTED_CHANGE_MESSAGE}: "
            f"type={change_type!r} result={change_result!r}"
        )
        raise StreamEventContractError(message)
    try:
        instance = apply_instance_callback(
            process_instance_id=process_instance_id,
            status=status,
        )
    except ApprovalInstanceNotFoundError:
        # 该审批实例不属于 EasyAuth(例如企业内其他流程), 记录在案即可。
        return StreamEventOutcome(
            status=STREAM_EVENT_STATUS_SKIPPED,
            result={
                "reason": SKIP_REASON_INSTANCE_NOT_FOUND,
                "process_instance_id": process_instance_id,
            },
        )
    return StreamEventOutcome(
        status=STREAM_EVENT_STATUS_PROCESSED,
        result={
            "process_instance_id": process_instance_id,
            "instance_id": str(instance.id),
            "status": instance.status,
        },
    )


def _finalize_event(
    event: DingTalkStreamEvent,
    *,
    status: str,
    result: dict[str, JsonValue] | None = None,
    error: str = "",
) -> None:
    event.status = status
    event.result = result or {}
    event.error = error
    event.processed_at = timezone.now()
    event.save(update_fields=["status", "result", "error", "processed_at", "updated_at"])


def _data_string(data: dict[str, JsonValue], key: str) -> str:
    value = data.get(key)
    return value if isinstance(value, str) else ""


def _data_string_list(data: dict[str, JsonValue], key: str) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))

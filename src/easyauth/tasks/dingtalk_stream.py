from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol, cast

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
)
from easyauth.integrations.authentik.directory_refresh import (
    DIRECTORY_REFRESH_MAX_RETRIES,
    DIRECTORY_REFRESH_RETRY_BACKOFF_MAX_SECONDS,
    REFRESH_RETRY_BUDGET_SECONDS,
    DirectoryRefreshHooks,
    refresh_dingtalk_directory,
    refresh_trigger_marker_ttl,
)
from easyauth.integrations.models import (
    STREAM_EVENT_STATUS_FAILED,
    STREAM_EVENT_STATUS_PROCESSED,
    STREAM_EVENT_STATUS_RECEIVED,
    STREAM_EVENT_STATUS_SKIPPED,
    DingTalkStreamEvent,
)
from easyauth.outbox.services import enqueue_task
from easyauth.tasks.dingtalk_stream_markers import (
    REFRESH_MAX_CONSECUTIVE_REQUEUES,
    REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS,
    REFRESH_TASK_TIME_LIMIT_SECONDS,
    accumulate_refresh_user_ids,
    acquire_running_lock,
    claim_exhaustion_followup,
    clear_dept_event_token,
    clear_exhaustion_followup,
    consume_trailing_needed,
    delete_pending_marker,
    delete_requeue_count,
    extend_running_lock,
    increment_requeue_count,
    mark_dept_event_pending,
    mark_sync_triggered,
    mark_trailing_needed,
    peek_pending_user_ids,
    pending_marker_exists,
    read_dept_event_token,
    refresh_countdown,
    refresh_exhaustion_followup_flag,
    release_running_lock,
    remove_sent_user_ids,
    running_lock_held,
    set_pending_marker,
    trailing_refresh_should_trigger,
)
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
    from collections.abc import Sequence

    from easyauth.applications.ops_models import JsonValue
    from easyauth.integrations.authentik.directory_sync import AuthentikDirectorySyncResult

logger = logging.getLogger(__name__)

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
# 仅 user_* 事件体带钉钉 userId 列表; 部门事件靠增量树遍历覆盖, 不必传 user_ids。
USER_DIRECTORY_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "user_add_org",
        "user_modify_org",
        "user_leave_org",
        "user_active_org",
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

_REFRESH_COUNT_KEYS: Final[tuple[str, ...]] = (
    "department_count",
    "user_count",
    "org_context_count",
    "status_applied_count",
    "departed_count",
    "revoked_count",
    "tombstoned_user_count",
)

DIRECTORY_EVENT_MISSING_CORP_MESSAGE: Final = "钉钉目录事件缺少 corp_id。"
BPMS_EVENT_MISSING_INSTANCE_MESSAGE: Final = "钉钉审批事件缺少 processInstanceId。"
BPMS_EVENT_UNSUPPORTED_CHANGE_MESSAGE: Final = "钉钉审批事件状态组合无法识别。"
_EXHAUSTED_FOLLOWUP_SCHEDULED_MESSAGE: Final = (
    "Authentik 目录刷新重试预算耗尽, 已安排一次延迟补刷新; corp=%s countdown=%s"
)
_EXHAUSTED_FOLLOWUP_SKIPPED_MESSAGE: Final = (
    "Authentik 目录刷新重试预算耗尽, 不再安排新的延迟补刷新; corp=%s"
)
_EXHAUSTED_FOLLOWUP_STOPPED_MESSAGE: Final = (
    "Authentik 目录刷新延迟补刷新重试预算耗尽, 不再安排下一次; corp=%s"
)

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


class _DirectoryRefreshRequest(Protocol):
    called_directly: bool
    retries: int


class _BoundDirectoryRefreshTask(Protocol):
    max_retries: int
    request: _DirectoryRefreshRequest


class StreamEventContractError(Exception):
    """事件载荷违反钉钉数据契约, 无法处理且重试无意义。"""


@dataclass(frozen=True, slots=True)
class StreamEventOutcome:
    status: str
    result: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _RefreshExit:
    skipped: bool
    outcome: AuthentikDirectorySyncResult | None


def request_directory_refresh(
    corp_id: str,
    *,
    source_event_id: str,
    user_ids: Sequence[str] = (),
    trailing: bool = False,
    is_followup: bool = False,
) -> bool:
    accumulate_refresh_user_ids(corp_id, user_ids)
    if running_lock_held(corp_id):
        mark_trailing_needed(corp_id)
        return False
    if pending_marker_exists(corp_id):
        return False
    _ = enqueue_task(
        event_key=f"dingtalk-directory-refresh:{corp_id}:{source_event_id}",
        task_name=DIRECTORY_REFRESH_TASK_NAME,
        args=[corp_id],
        kwargs=_refresh_task_kwargs(trailing=trailing, is_followup=is_followup),
        countdown=refresh_countdown(corp_id),
    )
    transaction.on_commit(lambda: set_pending_marker(corp_id))
    return True


def _refresh_task_kwargs(*, trailing: bool, is_followup: bool) -> dict[str, JsonValue] | None:
    payload: dict[str, JsonValue] = {}
    if trailing:
        payload["trailing"] = True
    if is_followup:
        payload["is_followup"] = True
    if not payload:
        return None
    return payload


# retry_backoff=True 的因子是 1, 与 REFRESH_RETRY_BUDGET_SECONDS 的算术一致。
@shared_task(
    name=DIRECTORY_REFRESH_TASK_NAME,
    bind=True,
    autoretry_for=(AuthentikDirectoryError,),
    retry_backoff=True,
    retry_backoff_max=DIRECTORY_REFRESH_RETRY_BACKOFF_MAX_SECONDS,
    retry_jitter=True,
    max_retries=DIRECTORY_REFRESH_MAX_RETRIES,
    soft_time_limit=REFRESH_TASK_SOFT_TIME_LIMIT_SECONDS,
    time_limit=REFRESH_TASK_TIME_LIMIT_SECONDS,
    acks_late=True,
)
def refresh_dingtalk_directory_task(
    self: _BoundDirectoryRefreshTask,
    corp_id: str,
    *,
    trailing: bool = False,
    # 已在 broker 里的旧消息没有该参数, 缺省按普通刷新处理。
    is_followup: bool = False,
) -> dict[str, int]:
    _touch_attempt_markers(corp_id)
    try:
        return _refresh_directory_for_corp(
            corp_id,
            trailing=trailing,
            is_followup=is_followup,
        )
    except AuthentikDirectoryError:
        if _retries_exhausted(self):
            _schedule_exhaustion_followup(corp_id, is_followup=is_followup)
        raise


def _touch_attempt_markers(corp_id: str) -> None:
    # 每次尝试开头续期。长等待不会把触发基线或去重标志耗尽; 没有则不新建。
    refresh_trigger_marker_ttl(corp_id)
    refresh_exhaustion_followup_flag(corp_id)


def _retries_exhausted(task: _BoundDirectoryRefreshTask) -> bool:
    # 直接调用(测试、eager 的 called_directly)会立刻把异常抛回, 不是预算耗尽。
    if task.request.called_directly:
        return False
    return task.request.retries >= task.max_retries


def _refresh_directory_for_corp(
    corp_id: str,
    *,
    trailing: bool,
    is_followup: bool,
) -> dict[str, int]:
    token = acquire_running_lock(corp_id)
    if token is None:
        mark_trailing_needed(corp_id)
        return _empty_refresh_counts()
    try:
        exit_state = _locked_refresh(corp_id, token, trailing=trailing)
    finally:
        release_running_lock(corp_id, token)
    if exit_state.skipped:
        clear_exhaustion_followup(corp_id)
        _arm_trailing_after_success(corp_id)
        return _empty_refresh_counts()
    return _finish_directory_refresh(
        corp_id,
        exit_state.outcome,
        is_followup=is_followup,
    )


def _locked_refresh(corp_id: str, token: str, *, trailing: bool) -> _RefreshExit:
    delete_pending_marker(corp_id)
    if trailing and not trailing_refresh_should_trigger(corp_id):
        return _RefreshExit(skipped=True, outcome=None)
    outcome = _run_directory_refresh(corp_id, peek_pending_user_ids(corp_id), token)
    return _RefreshExit(skipped=False, outcome=outcome)


def _finish_directory_refresh(
    corp_id: str,
    outcome: AuthentikDirectorySyncResult | None,
    *,
    is_followup: bool,
) -> dict[str, int]:
    if outcome is None:
        _ = consume_trailing_needed(corp_id)
        return _reschedule_after_not_queued(corp_id, is_followup=is_followup)
    delete_requeue_count(corp_id)
    clear_exhaustion_followup(corp_id)
    _arm_trailing_after_success(corp_id)
    return {key: cast("int", getattr(outcome, key)) for key in _REFRESH_COUNT_KEYS}


def _run_directory_refresh(
    corp_id: str,
    user_ids: tuple[str, ...],
    token: str,
) -> AuthentikDirectorySyncResult | None:
    accepted = False
    # 只在真正 trigger_sync 之前采样。恢复一条已经 queued 的同步时不采样,
    # 这样等待期间新到的部门事件不会被这次成功 apply 清掉。
    dept_token: str | None = None

    def _before_trigger() -> None:
        nonlocal dept_token
        dept_token = read_dept_event_token(corp_id)

    def _on_accepted(accepted_ids: tuple[str, ...]) -> None:
        nonlocal accepted
        accepted = True
        remove_sent_user_ids(corp_id, accepted_ids)
        if dept_token is not None:
            clear_dept_event_token(corp_id, dept_token)
        mark_sync_triggered(corp_id)

    def _before_apply() -> None:
        extend_running_lock(corp_id, token)

    client = AuthentikDirectoryClient.from_settings()
    result = refresh_dingtalk_directory(
        client,
        corp_id,
        user_ids=user_ids,
        hooks=DirectoryRefreshHooks(
            on_accepted_user_ids=_on_accepted,
            before_trigger=_before_trigger,
            before_apply=_before_apply,
            peek_user_ids=lambda: peek_pending_user_ids(corp_id),
        ),
    )
    if result is not None and not accepted:
        _on_accepted(user_ids)
    return result


def _reschedule_after_not_queued(corp_id: str, *, is_followup: bool) -> dict[str, int]:
    requeue_count = increment_requeue_count(corp_id)
    if requeue_count > REFRESH_MAX_CONSECUTIVE_REQUEUES:
        _schedule_exhaustion_followup(corp_id, is_followup=is_followup)
        return _empty_refresh_counts()
    _ = request_directory_refresh(
        corp_id,
        source_event_id=f"requeue-{requeue_count}-{time.time_ns()}",
        user_ids=(),
        is_followup=is_followup,
    )
    return _empty_refresh_counts()


def _schedule_exhaustion_followup(corp_id: str, *, is_followup: bool) -> None:
    # 补刷新自己耗尽时只记一次错误并停止。id 留在 pending, 等下一次事件;
    # 每日全量同步是最后兜底, 不再排下一轮延迟补刷新。
    if is_followup:
        logger.error(_EXHAUSTED_FOLLOWUP_STOPPED_MESSAGE, corp_id)
        return
    if not claim_exhaustion_followup(corp_id):
        logger.error(_EXHAUSTED_FOLLOWUP_SKIPPED_MESSAGE, corp_id)
        return
    refresh_trigger_marker_ttl(corp_id)
    _ = enqueue_task(
        event_key=f"dingtalk-directory-refresh-followup:{corp_id}:{time.time_ns()}",
        task_name=DIRECTORY_REFRESH_TASK_NAME,
        args=[corp_id],
        kwargs=_refresh_task_kwargs(trailing=True, is_followup=True),
        countdown=float(REFRESH_RETRY_BUDGET_SECONDS),
    )
    logger.error(
        _EXHAUSTED_FOLLOWUP_SCHEDULED_MESSAGE,
        corp_id,
        REFRESH_RETRY_BUDGET_SECONDS,
    )


def _arm_trailing_after_success(corp_id: str) -> None:
    trailing = consume_trailing_needed(corp_id)
    if not trailing and not peek_pending_user_ids(corp_id):
        return
    _ = request_directory_refresh(
        corp_id,
        source_event_id=f"trailing-{time.time_ns()}",
        user_ids=(),
        trailing=True,
    )


def _empty_refresh_counts() -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(_REFRESH_COUNT_KEYS, 0)
    return counts


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
    user_ids = _data_string_list(event.data, "userId") or _data_string_list(event.data, "UserId")
    pending_ids = user_ids if event.event_type in USER_DIRECTORY_EVENT_TYPES else ()
    if event.event_type not in USER_DIRECTORY_EVENT_TYPES:
        transaction.on_commit(lambda: mark_dept_event_pending(corp_id))
    refresh_queued = request_directory_refresh(
        corp_id,
        source_event_id=event.event_id,
        user_ids=pending_ids,
    )
    result: dict[str, JsonValue] = {
        "corp_id": corp_id,
        "refresh_queued": refresh_queued,
    }
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

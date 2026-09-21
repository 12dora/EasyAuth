from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, cast

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from easyauth.integrations.authentik.directory_client import (
    AuthentikDirectoryClient,
    AuthentikDirectoryError,
)
from easyauth.integrations.authentik.directory_refresh import (
    REFRESH_WAIT_TIMEOUT_SECONDS,
    refresh_dingtalk_directory,
)
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
    from collections.abc import Callable, Sequence

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

# 事件风暴合并与钉钉计费: 30s 合并窗口、queued=true 后 120s 冷却、全程 running 锁
# (TTL ≥ Authentik 等待+余量)。锁内事件只累积 id 并标记 trailing, 当前刷新结束且过
# 冷却后再触发恰好一次。user_ids 只 peek, queued=true 后删除本次送出的 id。
REFRESH_PENDING_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-pending:{corp_id}"
REFRESH_USER_IDS_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-user-ids:{corp_id}"
REFRESH_USER_IDS_LOCK_CACHE_KEY_TEMPLATE: Final = (
    "easyauth:dingtalk:stream:refresh-user-ids-lock:{corp_id}"
)
REFRESH_LAST_TRIGGERED_CACHE_KEY_TEMPLATE: Final = (
    "easyauth:dingtalk:stream:refresh-last-triggered:{corp_id}"
)
REFRESH_REQUEUE_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-requeue:{corp_id}"
REFRESH_RUNNING_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-running:{corp_id}"
REFRESH_TRAILING_CACHE_KEY_TEMPLATE: Final = "easyauth:dingtalk:stream:refresh-trailing:{corp_id}"
REFRESH_COALESCE_SECONDS: Final = 30
REFRESH_PENDING_TTL_SECONDS: Final = 600
REFRESH_MIN_INTERVAL_SECONDS: Final = 120
REFRESH_RUNNING_LOCK_TTL_SECONDS: Final = (
    int(REFRESH_WAIT_TIMEOUT_SECONDS) + REFRESH_MIN_INTERVAL_SECONDS
)
# Authentik 增量同步 user_ids 上限(与 REST 契约一致); 超出部分由每日全量同步兜底。
REFRESH_USER_IDS_MAX: Final = 200
# queued=false 时最多连续再调度次数, 避免在 Authentik 长事务上忙等烧配额。
REFRESH_MAX_CONSECUTIVE_REQUEUES: Final = 3
REFRESH_USER_IDS_LOCK_TTL_SECONDS: Final = 5
REFRESH_USER_IDS_LOCK_ATTEMPTS: Final = 20
REFRESH_USER_IDS_LOCK_SLEEP_SECONDS: Final = 0.05
REFRESH_USER_IDS_LOCK_FAILED_MESSAGE: Final = "钉钉目录刷新 user_ids 缓存锁获取失败。"
REFRESH_CACHE_TYPE_MESSAGE: Final = "钉钉目录刷新缓存值类型无效。"
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


def _corp_key(template: str, corp_id: str) -> str:
    return template.format(corp_id=corp_id)


def request_directory_refresh(
    corp_id: str,
    *,
    source_event_id: str,
    user_ids: Sequence[str] = (),
) -> bool:
    _accumulate_refresh_user_ids(corp_id, user_ids)
    if _running_remaining_seconds(corp_id) > 0:
        _mark_trailing_needed(corp_id)
        return False
    if _pending_marker_exists(corp_id):
        return False
    _ = enqueue_task(
        event_key=f"dingtalk-directory-refresh:{corp_id}:{source_event_id}",
        task_name=DIRECTORY_REFRESH_TASK_NAME,
        args=[corp_id],
        countdown=_refresh_countdown(corp_id),
    )
    transaction.on_commit(lambda: _set_pending_marker(corp_id))
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
    if not _acquire_running_lock(corp_id):
        _mark_trailing_needed(corp_id)
        return _empty_refresh_counts()
    try:
        _ = cache.delete(_corp_key(REFRESH_PENDING_CACHE_KEY_TEMPLATE, corp_id))
        outcome = _run_directory_refresh(corp_id, _peek_pending_user_ids(corp_id))
    finally:
        _release_running_lock(corp_id)
    return _finish_directory_refresh(corp_id, outcome)


def _finish_directory_refresh(
    corp_id: str,
    outcome: AuthentikDirectorySyncResult | None,
) -> dict[str, int]:
    if outcome is None:
        _ = _consume_trailing_needed(corp_id)
        return _reschedule_after_not_queued(corp_id)
    _ = cache.delete(_corp_key(REFRESH_REQUEUE_CACHE_KEY_TEMPLATE, corp_id))
    _arm_trailing_after_success(corp_id)
    return {key: cast("int", getattr(outcome, key)) for key in _REFRESH_COUNT_KEYS}


def _run_directory_refresh(
    corp_id: str,
    user_ids: tuple[str, ...],
) -> AuthentikDirectorySyncResult | None:
    accepted = False

    def _on_accepted(accepted_ids: tuple[str, ...]) -> None:
        nonlocal accepted
        accepted = True
        _remove_sent_user_ids(corp_id, accepted_ids)
        _mark_sync_triggered(corp_id)

    client = AuthentikDirectoryClient.from_settings()
    result = refresh_dingtalk_directory(
        client,
        corp_id,
        user_ids=user_ids,
        on_accepted_user_ids=_on_accepted,
    )
    if result is not None and not accepted:
        _on_accepted(user_ids)
    return result


def _reschedule_after_not_queued(corp_id: str) -> dict[str, int]:
    requeue_count = _increment_requeue_count(corp_id)
    if requeue_count > REFRESH_MAX_CONSECUTIVE_REQUEUES:
        logger.error(
            "Authentik 目录同步连续 queued=false 超过 %s 次, 停止再调度; corp=%s",
            REFRESH_MAX_CONSECUTIVE_REQUEUES,
            corp_id,
        )
        return _empty_refresh_counts()
    _ = request_directory_refresh(
        corp_id,
        source_event_id=f"requeue-{requeue_count}-{time.time_ns()}",
        user_ids=(),
    )
    return _empty_refresh_counts()


def _arm_trailing_after_success(corp_id: str) -> None:
    trailing = _consume_trailing_needed(corp_id)
    if not trailing and not _peek_pending_user_ids(corp_id):
        return
    _ = request_directory_refresh(
        corp_id,
        source_event_id=f"trailing-{time.time_ns()}",
        user_ids=(),
    )


def _empty_refresh_counts() -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(_REFRESH_COUNT_KEYS, 0)
    return counts


def _refresh_countdown(corp_id: str) -> float:
    remaining = max(
        _timestamp_remaining_seconds(
            cast(
                "object",
                cache.get(_corp_key(REFRESH_LAST_TRIGGERED_CACHE_KEY_TEMPLATE, corp_id)),
            ),
            extra_seconds=float(REFRESH_MIN_INTERVAL_SECONDS),
        ),
        _running_remaining_seconds(corp_id),
    )
    if remaining > 0:
        return remaining
    return float(REFRESH_COALESCE_SECONDS)


def _running_remaining_seconds(corp_id: str) -> float:
    return _timestamp_remaining_seconds(
        cast("object", cache.get(_corp_key(REFRESH_RUNNING_CACHE_KEY_TEMPLATE, corp_id))),
    )


def _timestamp_remaining_seconds(raw: object, *, extra_seconds: float = 0.0) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    remaining = float(raw) + extra_seconds - time.time()
    return remaining if remaining > 0 else 0.0


def _mark_sync_triggered(corp_id: str) -> None:
    cache.set(
        _corp_key(REFRESH_LAST_TRIGGERED_CACHE_KEY_TEMPLATE, corp_id),
        time.time(),
        timeout=REFRESH_MIN_INTERVAL_SECONDS,
    )


def _acquire_running_lock(corp_id: str) -> bool:
    expires_at = time.time() + float(REFRESH_RUNNING_LOCK_TTL_SECONDS)
    return cache.add(
        _corp_key(REFRESH_RUNNING_CACHE_KEY_TEMPLATE, corp_id),
        expires_at,
        timeout=REFRESH_RUNNING_LOCK_TTL_SECONDS,
    )


def _release_running_lock(corp_id: str) -> None:
    _ = cache.delete(_corp_key(REFRESH_RUNNING_CACHE_KEY_TEMPLATE, corp_id))


def _set_pending_marker(corp_id: str) -> None:
    _ = cache.add(
        _corp_key(REFRESH_PENDING_CACHE_KEY_TEMPLATE, corp_id),
        "1",
        timeout=REFRESH_PENDING_TTL_SECONDS,
    )


def _pending_marker_exists(corp_id: str) -> bool:
    raw = cast("object", cache.get(_corp_key(REFRESH_PENDING_CACHE_KEY_TEMPLATE, corp_id)))
    if raw is None:
        return False
    if raw != "1":
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return True


def _mark_trailing_needed(corp_id: str) -> None:
    cache.set(
        _corp_key(REFRESH_TRAILING_CACHE_KEY_TEMPLATE, corp_id),
        "1",
        timeout=REFRESH_PENDING_TTL_SECONDS,
    )


def _consume_trailing_needed(corp_id: str) -> bool:
    key = _corp_key(REFRESH_TRAILING_CACHE_KEY_TEMPLATE, corp_id)
    raw = cast("object", cache.get(key))
    _ = cache.delete(key)
    if raw is None:
        return False
    if raw != "1":
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return True


def _increment_requeue_count(corp_id: str) -> int:
    key = _corp_key(REFRESH_REQUEUE_CACHE_KEY_TEMPLATE, corp_id)
    if cache.add(key, 1, timeout=REFRESH_PENDING_TTL_SECONDS):
        return 1
    try:
        count = cast("object", cache.incr(key))
    except ValueError:
        cache.set(key, 1, timeout=REFRESH_PENDING_TTL_SECONDS)
        return 1
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    return count


def _accumulate_refresh_user_ids(corp_id: str, user_ids: Sequence[str]) -> None:
    incoming = [item for item in user_ids if item]
    if not incoming:
        return

    def _merge(current: list[str]) -> list[str]:
        return _bounded_user_ids(corp_id, [*current, *incoming])

    _ = _with_user_ids_lock(corp_id, _merge)


def _peek_pending_user_ids(corp_id: str) -> tuple[str, ...]:
    peeked: list[str] = []

    def _copy(current: list[str]) -> list[str]:
        peeked.extend(current)
        return current

    _ = _with_user_ids_lock(corp_id, _copy)
    return tuple(peeked)


def _remove_sent_user_ids(corp_id: str, user_ids: Sequence[str]) -> None:
    sent = {item for item in user_ids if item}
    if not sent:
        return

    def _drop(current: list[str]) -> list[str]:
        return [item for item in current if item not in sent]

    _ = _with_user_ids_lock(corp_id, _drop)


def _bounded_user_ids(corp_id: str, user_ids: list[str]) -> list[str]:
    merged = list(dict.fromkeys(user_ids))
    overflow = len(merged) - REFRESH_USER_IDS_MAX
    if overflow <= 0:
        return merged
    logger.warning(
        "钉钉目录刷新 user_ids 超过 %s, 只保留先到的 %s 个, 其余由每日全量兜底; corp=%s dropped=%s",
        REFRESH_USER_IDS_MAX,
        REFRESH_USER_IDS_MAX,
        corp_id,
        overflow,
    )
    return merged[:REFRESH_USER_IDS_MAX]


def _with_user_ids_lock(
    corp_id: str,
    mutator: Callable[[list[str]], list[str]],
) -> list[str]:
    lock_key = _corp_key(REFRESH_USER_IDS_LOCK_CACHE_KEY_TEMPLATE, corp_id)
    ids_key = _corp_key(REFRESH_USER_IDS_CACHE_KEY_TEMPLATE, corp_id)
    for _attempt in range(REFRESH_USER_IDS_LOCK_ATTEMPTS):
        if cache.add(lock_key, "1", timeout=REFRESH_USER_IDS_LOCK_TTL_SECONDS):
            try:
                updated = mutator(_read_cached_user_ids(ids_key))
                _write_cached_user_ids(ids_key, updated)
                return updated
            finally:
                _ = cache.delete(lock_key)
        time.sleep(REFRESH_USER_IDS_LOCK_SLEEP_SECONDS)
    raise RuntimeError(REFRESH_USER_IDS_LOCK_FAILED_MESSAGE)


def _read_cached_user_ids(ids_key: str) -> list[str]:
    raw = cast("object", cache.get(ids_key))
    if raw is None:
        return []
    if not isinstance(raw, list | tuple):
        raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
    items: list[str] = []
    for item in cast("list[object] | tuple[object, ...]", raw):
        if not isinstance(item, str):
            raise TypeError(REFRESH_CACHE_TYPE_MESSAGE)
        if item:
            items.append(item)
    return items


def _write_cached_user_ids(ids_key: str, user_ids: list[str]) -> None:
    if not user_ids:
        _ = cache.delete(ids_key)
        return
    cache.set(ids_key, user_ids, timeout=REFRESH_PENDING_TTL_SECONDS)


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

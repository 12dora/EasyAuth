from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps
from typing import TYPE_CHECKING, Final, cast, final, override

from asgiref.sync import sync_to_async
from dingtalk_stream import AckMessage, Credential, DingTalkStreamClient, EventHandler
from django.db import transaction

from easyauth.applications.integration_settings import dingtalk_runtime_config
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.config.runtime_health import STREAM_ACK_HEARTBEAT, mark_heartbeat
from easyauth.integrations.dingtalk.api_client import DingTalkNotConfiguredError
from easyauth.integrations.models import DingTalkStreamEvent
from easyauth.outbox.services import enqueue_task

if TYPE_CHECKING:
    from dingtalk_stream import EventMessage

    from easyauth.applications.ops_models import JsonValue

logger = logging.getLogger(__name__)

STREAM_EVENT_MISSING_IDENTITY_MESSAGE: Final = "钉钉 Stream 事件缺少 event_id 或 event_type。"
STREAM_EVENT_CONFLICT_MESSAGE: Final = "钉钉 Stream 事件 event_id 与已收事件冲突。"
ACK_OK_MESSAGE: Final = "OK"
ACK_DUPLICATE_MESSAGE: Final = "duplicate"
ACK_PERSIST_FAILED_MESSAGE: Final = "event persist failed"
AUDIT_ACTION_STREAM_EVENT_CONFLICT: Final = "dingtalk_stream_event_conflict"
PROCESS_STREAM_EVENT_TASK_NAME: Final = "easyauth.dingtalk_stream.process_event"


class StreamEventIdentityError(ValueError):
    def __init__(self) -> None:
        super().__init__(STREAM_EVENT_MISSING_IDENTITY_MESSAGE)


class StreamEventConflictError(ValueError):
    def __init__(self) -> None:
        super().__init__(STREAM_EVENT_CONFLICT_MESSAGE)


@dataclass(frozen=True, slots=True)
class StreamEventReceipt:
    event_pk: int
    created: bool


def record_stream_event(
    *,
    event_id: str,
    event_type: str,
    corp_id: str,
    born_time_ms: int | None,
    data: dict[str, JsonValue],
) -> StreamEventReceipt:
    """把 Stream 事件写入收件箱并排队处理任务; 以 event_id + 业务指纹幂等。"""
    if not event_id or not event_type:
        raise StreamEventIdentityError
    born_at = (
        datetime.fromtimestamp(born_time_ms / 1000, tz=UTC) if born_time_ms is not None else None
    )
    data_sha256 = canonical_stream_data_sha256(data)
    conflict_metadata: dict[str, JsonValue] | None = None
    conflict_event_id = ""
    with transaction.atomic():
        event, created = DingTalkStreamEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                "event_type": event_type,
                "corp_id": corp_id,
                "born_at": born_at,
                "data": data,
                "data_sha256": data_sha256,
            },
        )
        event_pk = cast("int", event.pk)
        if not created:
            conflict_metadata = _stream_event_conflict_metadata(
                event,
                event_type=event_type,
                corp_id=corp_id,
                born_at=born_at,
                data_sha256=data_sha256,
            )
            if conflict_metadata is not None:
                conflict_event_id = event.event_id
            else:
                # 重投也执行幂等写入: 可修补历史上业务行已存在但消息发布失败的缺口。
                _ = enqueue_task(
                    event_key=f"dingtalk-stream:{event_id}",
                    task_name=PROCESS_STREAM_EVENT_TASK_NAME,
                    args=[event_pk],
                )
        else:
            _ = enqueue_task(
                event_key=f"dingtalk-stream:{event_id}",
                task_name=PROCESS_STREAM_EVENT_TASK_NAME,
                args=[event_pk],
            )
    if conflict_metadata is not None:
        return _raise_stream_event_conflict(conflict_event_id, conflict_metadata)
    return StreamEventReceipt(event_pk=event_pk, created=created)


def canonical_stream_data_sha256(data: dict[str, JsonValue]) -> str:
    canonical = dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def _stream_event_conflict_metadata(
    event: DingTalkStreamEvent,
    *,
    event_type: str,
    corp_id: str,
    born_at: datetime | None,
    data_sha256: str,
) -> dict[str, JsonValue] | None:
    stored_hash = event.data_sha256 or canonical_stream_data_sha256(event.data)
    if not event.data_sha256:
        event.data_sha256 = stored_hash
        event.save(update_fields=["data_sha256", "updated_at"])
    same_identity = (
        event.event_type == event_type
        and event.corp_id == corp_id
        and event.born_at == born_at
        and stored_hash == data_sha256
    )
    if same_identity:
        return None
    return {
        "stored_event_type": event.event_type,
        "incoming_event_type": event_type,
        "stored_corp_id": event.corp_id,
        "incoming_corp_id": corp_id,
        "stored_born_at": event.born_at.isoformat() if event.born_at else "",
        "incoming_born_at": born_at.isoformat() if born_at else "",
        "stored_data_sha256": stored_hash,
        "incoming_data_sha256": data_sha256,
    }


def _raise_stream_event_conflict(
    event_id: str,
    metadata: dict[str, JsonValue],
) -> StreamEventReceipt:
    _ = AuditService.record(
        AuditRecord(
            actor_type="system",
            actor_id="dingtalk_stream",
            action=AUDIT_ACTION_STREAM_EVENT_CONFLICT,
            target_type="dingtalk_stream_event",
            target_id=event_id,
            metadata=metadata,
        )
    )
    raise StreamEventConflictError


@final
class EasyAuthDingTalkEventHandler(EventHandler):
    """收下所有 EVENT 推送: 先持久化, 落库成功才 ACK。

    钉钉按 ACK 结果决定是否重投; 持久化失败时必须返回系统异常, 让钉钉稍后
    重投同一 event_id, 而不是 ACK 后把事件永久丢失。
    """

    @override
    async def process(self, event: EventMessage) -> tuple[int, str]:
        headers = event.headers
        event_id = headers.event_id if isinstance(headers.event_id, str) else ""
        event_type = headers.event_type if isinstance(headers.event_type, str) else ""
        corp_id = headers.event_corp_id if isinstance(headers.event_corp_id, str) else ""
        born_time_ms = headers.event_born_time if isinstance(headers.event_born_time, int) else None
        data = cast("dict[str, JsonValue]", event.data)
        try:
            receipt = await sync_to_async(record_stream_event)(
                event_id=event_id,
                event_type=event_type,
                corp_id=corp_id,
                born_time_ms=born_time_ms,
                data=data,
            )
        except Exception:
            # 不能吞: 记录完整异常后向钉钉报系统异常, 事件将由钉钉重投, 不会丢失。
            logger.exception(
                "钉钉 Stream 事件持久化失败: event_id=%s event_type=%s",
                event_id,
                event_type,
            )
            return AckMessage.STATUS_SYSTEM_EXCEPTION, ACK_PERSIST_FAILED_MESSAGE
        logger.info(
            "钉钉 Stream 事件已接收: event_id=%s event_type=%s corp_id=%s created=%s",
            event_id,
            event_type,
            corp_id,
            receipt.created,
        )
        await sync_to_async(mark_heartbeat)(STREAM_ACK_HEARTBEAT)
        return AckMessage.STATUS_OK, ACK_OK_MESSAGE if receipt.created else ACK_DUPLICATE_MESSAGE


def build_stream_client() -> DingTalkStreamClient:
    """按数据库/环境变量里的钉钉凭证构建 Stream 客户端并注册事件处理器。"""
    config = dingtalk_runtime_config()
    if not config.is_configured():
        raise DingTalkNotConfiguredError
    client = DingTalkStreamClient(Credential(config.app_key, config.app_secret))
    client.register_all_event_handler(EasyAuthDingTalkEventHandler())
    return client

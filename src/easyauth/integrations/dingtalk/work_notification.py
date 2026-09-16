from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from easyauth.integrations.dingtalk.errors import DingTalkApiRequestError

if TYPE_CHECKING:
    from easyauth.integrations.dingtalk.errors import DingTalkJson

OAPI_ASYNC_SEND_PATH: Final = "/topapi/message/corpconversation/asyncsend_v2"
OAPI_GET_SEND_PROGRESS_PATH: Final = "/topapi/message/corpconversation/getsendprogress"
OAPI_GET_SEND_RESULT_PATH: Final = "/topapi/message/corpconversation/getsendresult"
# 官方 userid_list 上限, 同时保住 getsendresult 回执能力。
WORK_NOTIFICATION_MAX_USERIDS: Final = 100
WORK_NOTIFICATION_PROGRESS_MAX_PERCENT: Final = 100


@dataclass(frozen=True, slots=True)
class DingTalkSendProgress:
    status: int
    progress_in_percent: int | None = None


@dataclass(frozen=True, slots=True)
class DingTalkForbiddenReceipt:
    userid: str
    code: int | None


@dataclass(frozen=True, slots=True)
class DingTalkSendResult:
    invalid_user_ids: frozenset[str]
    failed_user_ids: frozenset[str]
    forbidden_user_ids: frozenset[str]
    read_user_ids: frozenset[str]
    unread_user_ids: frozenset[str]
    forbidden_receipts: tuple[DingTalkForbiddenReceipt, ...]


def parse_send_progress(progress: DingTalkJson) -> DingTalkSendProgress:
    status = progress.get("status")
    if isinstance(status, bool) or not isinstance(status, int):
        message = "钉钉发送进度 status 缺失或类型无效。"
        raise DingTalkApiRequestError(message)
    percent = progress.get("progress_in_percent")
    if percent is None:
        parsed_percent = None
    elif (
        isinstance(percent, bool)
        or not isinstance(percent, int)
        or not 0 <= percent <= WORK_NOTIFICATION_PROGRESS_MAX_PERCENT
    ):
        message = "钉钉发送进度 progress_in_percent 类型无效。"
        raise DingTalkApiRequestError(message)
    else:
        parsed_percent = percent
    return DingTalkSendProgress(status=status, progress_in_percent=parsed_percent)


def parse_send_result(send_result: DingTalkJson) -> DingTalkSendResult:
    return DingTalkSendResult(
        invalid_user_ids=_required_userid_set(send_result, "invalid_user_id_list"),
        failed_user_ids=_required_userid_set(send_result, "failed_user_id_list"),
        forbidden_user_ids=_required_userid_set(send_result, "forbidden_user_id_list"),
        read_user_ids=_required_userid_set(send_result, "read_user_id_list"),
        unread_user_ids=_required_userid_set(send_result, "unread_user_id_list"),
        forbidden_receipts=_required_forbidden_receipts(send_result),
    )


def _required_userid_set(payload: DingTalkJson, field: str) -> frozenset[str]:
    raw = payload.get(field)
    if not isinstance(raw, list):
        message = f"钉钉发送结果 {field} 缺失或类型无效。"
        raise DingTalkApiRequestError(message)
    userids: set[str] = set()
    for item in cast("list[object]", raw):
        if not isinstance(item, str) or not item:
            message = f"钉钉发送结果 {field} 包含无效 userid。"
            raise DingTalkApiRequestError(message)
        userids.add(item)
    return frozenset(userids)


def _required_forbidden_receipts(payload: DingTalkJson) -> tuple[DingTalkForbiddenReceipt, ...]:
    raw = payload.get("forbidden_list")
    if not isinstance(raw, list):
        message = "钉钉发送结果 forbidden_list 缺失或类型无效。"
        raise DingTalkApiRequestError(message)
    receipts: list[DingTalkForbiddenReceipt] = []
    for raw_item in cast("list[object]", raw):
        if not isinstance(raw_item, dict):
            message = "钉钉发送结果 forbidden_list 包含无效条目。"
            raise DingTalkApiRequestError(message)
        item = cast("dict[str, object]", raw_item)
        userid = item.get("userid")
        if not isinstance(userid, str) or not userid:
            message = "钉钉发送结果 forbidden_list 条目缺少 userid。"
            raise DingTalkApiRequestError(message)
        code = _parse_forbidden_receipt_code(item.get("code"))
        receipts.append(DingTalkForbiddenReceipt(userid=userid, code=code))
    return tuple(receipts)


def _parse_forbidden_receipt_code(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        message = "钉钉发送结果 forbidden_list code 类型无效。"
        raise DingTalkApiRequestError(message)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    message = "钉钉发送结果 forbidden_list code 类型无效。"
    raise DingTalkApiRequestError(message)

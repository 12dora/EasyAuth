from __future__ import annotations

from dataclasses import dataclass
from json import dumps
from typing import TYPE_CHECKING, Final, cast

from easyauth.integrations.dingtalk.errors import DingTalkApiRequestError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from easyauth.integrations.dingtalk.errors import DingTalkJson

ROBOT_OTO_BATCH_SEND_PATH: Final = "/v1.0/robot/oToMessages/batchSend"
ROBOT_MSG_KEY_MARKDOWN: Final = "sampleMarkdown"
ROBOT_MSG_KEY_ACTION_CARD: Final = "sampleActionCard2"
ROBOT_ACTION_SINGLE_TITLE: Final = "查看详情"
# 服务号机器人 batchSend 单次 userIds 上限。
ROBOT_OTO_MAX_USERIDS: Final = 20


@dataclass(frozen=True, slots=True)
class DingTalkRobotOtoResult:
    process_query_key: str
    user_ids: tuple[str, ...]
    invalid_staff_ids: frozenset[str]
    flow_controlled_staff_ids: frozenset[str]


def chunk_robot_user_ids(user_ids: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """把机器人单聊收件人按官方上限拆批。"""
    return tuple(
        tuple(user_ids[index : index + ROBOT_OTO_MAX_USERIDS])
        for index in range(0, len(user_ids), ROBOT_OTO_MAX_USERIDS)
    )


def validated_robot_user_ids(user_ids: Sequence[object]) -> tuple[str, ...]:
    if not user_ids:
        message = "机器人单聊 userIds 不能为空。"
        raise DingTalkApiRequestError(message)
    normalized: list[str] = []
    for userid in user_ids:
        if not isinstance(userid, str) or not userid:
            message = "机器人单聊 userIds 包含无效 userid。"
            raise DingTalkApiRequestError(message)
        normalized.append(userid)
    return tuple(normalized)


def robot_msg_key_and_param(
    *,
    title: str,
    text: str,
    single_url: str,
    single_title: str,
) -> tuple[str, str]:
    if single_url:
        msg_key = ROBOT_MSG_KEY_ACTION_CARD
        param: dict[str, str] = {
            "title": title,
            "text": text,
            "singleTitle": single_title,
            "singleURL": single_url,
        }
    else:
        msg_key = ROBOT_MSG_KEY_MARKDOWN
        param = {"title": title, "text": text}
    return msg_key, dumps(param, ensure_ascii=False, separators=(",", ":"))


def parse_robot_oto_result(
    payload: DingTalkJson,
    user_ids: tuple[str, ...],
) -> DingTalkRobotOtoResult:
    process_query_key = payload.get("processQueryKey")
    if not isinstance(process_query_key, str) or not process_query_key:
        message = "钉钉机器人发送响应缺少 processQueryKey。"
        raise DingTalkApiRequestError(message)
    return DingTalkRobotOtoResult(
        process_query_key=process_query_key,
        user_ids=user_ids,
        invalid_staff_ids=_optional_staff_id_set(payload, "invalidStaffIdList"),
        flow_controlled_staff_ids=_optional_staff_id_set(
            payload,
            "flowControlledStaffIdList",
        ),
    )


def _optional_staff_id_set(payload: DingTalkJson, field: str) -> frozenset[str]:
    raw = payload.get(field)
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        message = f"钉钉机器人发送响应 {field} 类型无效。"
        raise DingTalkApiRequestError(message)
    staff_ids: set[str] = set()
    for item in cast("list[object]", raw):
        if not isinstance(item, str) or not item:
            message = f"钉钉机器人发送响应 {field} 包含无效 userid。"
            raise DingTalkApiRequestError(message)
        staff_ids.add(item)
    return frozenset(staff_ids)

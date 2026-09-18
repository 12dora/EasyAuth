"""人员 API 载荷的唯一出口: 账号类型、PersonRef、行字段。

所有向控制台/门户输出人员的序列化必须走 `person_payload` 或 `person_row_fields`,
避免各接口自行拼 dict 把 Authentik UUID 当成目录身份展示。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from easyauth.accounts.avatar_url import safe_avatar_url
from easyauth.accounts.directory_identity import has_directory_identity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.accounts.models import DingTalkUserMirror, UserMirror
    from easyauth.api.errors import JsonValue

ACCOUNT_KIND_DIRECTORY: Final = "directory"
ACCOUNT_KIND_DIRECTORY_UNREGISTERED: Final = "directory_unregistered"
ACCOUNT_KIND_LOCAL: Final = "local"
ACCOUNT_KIND_UNRESOLVED: Final = "unresolved"

type AccountKind = Literal["directory", "directory_unregistered", "local", "unresolved"]
type ResolvedAccountKind = Literal["directory", "local"]

__all__ = [
    "ACCOUNT_KIND_DIRECTORY",
    "ACCOUNT_KIND_DIRECTORY_UNREGISTERED",
    "ACCOUNT_KIND_LOCAL",
    "ACCOUNT_KIND_UNRESOLVED",
    "account_kind",
    "directory_unregistered_person_payload",
    "directory_user_triple",
    "person_payload",
    "person_row_fields",
    "unresolved_person_payload",
    "unresolved_person_row_fields",
]


def account_kind(user: UserMirror) -> ResolvedAccountKind:
    """已解析 UserMirror 的账号类型: 有钉钉绑定为 directory, 否则 local。"""
    # 目录用户的充分条件是钉钉绑定; 本地管理员与 Authentik 内建用户都没有 userid。
    if has_directory_identity(user):
        return ACCOUNT_KIND_DIRECTORY
    return ACCOUNT_KIND_LOCAL


def person_payload(user: UserMirror, labels: Mapping[str, str]) -> dict[str, JsonValue]:
    return {
        "user_id": user.authentik_user_id,
        "name": user.name,
        "department": labels.get(user.authentik_user_id, user.department),
        "account_kind": account_kind(user),
        "avatar_url": safe_avatar_url(user.avatar_url),
    }


def directory_user_triple(user: UserMirror) -> dict[str, JsonValue] | None:
    """UserMirror 的钉钉三元组; 无绑定时为 null, 不得编造。"""
    if not has_directory_identity(user):
        return None
    payload: dict[str, JsonValue] = {
        "source_slug": user.dingtalk_source_slug,
        "corp_id": user.dingtalk_corp_id,
        "user_id": user.dingtalk_userid,
    }
    return payload


def directory_unregistered_person_payload(
    user: DingTalkUserMirror,
    department: str,
) -> dict[str, JsonValue]:
    """通讯录在职且尚未镜像为 UserMirror 的人员选项。"""
    triple: dict[str, JsonValue] = {
        "source_slug": user.source_slug,
        "corp_id": user.corp_id,
        "user_id": user.user_id,
    }
    return {
        "user_id": None,
        "name": user.name,
        "department": department,
        "account_kind": ACCOUNT_KIND_DIRECTORY_UNREGISTERED,
        "avatar_url": safe_avatar_url(user.avatar),
        "directory_user": triple,
    }


def person_row_fields(
    user: UserMirror,
    labels: Mapping[str, str],
    prefix: str = "user_",
) -> dict[str, JsonValue]:
    return _row_fields(person_payload(user, labels), prefix)


def unresolved_person_payload(user_id: str) -> dict[str, JsonValue]:
    """成员关系等只存 authentik_user_id、尚无 UserMirror 时的人员形状。

    无法观察钉钉绑定, `account_kind` 为 `unresolved`, 不得推断为 `local`。
    姓名、部门与头像为空字符串。
    """
    return {
        "user_id": user_id,
        "name": "",
        "department": "",
        "account_kind": ACCOUNT_KIND_UNRESOLVED,
        "avatar_url": "",
    }


def unresolved_person_row_fields(user_id: str, prefix: str = "user_") -> dict[str, JsonValue]:
    return _row_fields(unresolved_person_payload(user_id), prefix)


def _row_fields(person: Mapping[str, JsonValue], prefix: str) -> dict[str, JsonValue]:
    return {
        f"{prefix}id": person["user_id"],
        f"{prefix}name": person["name"],
        f"{prefix}department": person["department"],
        f"{prefix}account_kind": person["account_kind"],
        f"{prefix}avatar_url": person["avatar_url"],
    }

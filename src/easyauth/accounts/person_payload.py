"""人员 API 载荷的唯一出口: 账号类型、PersonRef、行字段。

所有向控制台/门户输出人员的序列化必须走 `person_payload` 或 `person_row_fields`,
避免各接口自行拼 dict 把 Authentik UUID 当成目录身份展示。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from easyauth.accounts.directory_identity import has_directory_identity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from easyauth.accounts.models import UserMirror
    from easyauth.api.errors import JsonValue

ACCOUNT_KIND_DIRECTORY: Final = "directory"
ACCOUNT_KIND_LOCAL: Final = "local"

type AccountKind = Literal["directory", "local"]

__all__ = [
    "ACCOUNT_KIND_DIRECTORY",
    "ACCOUNT_KIND_LOCAL",
    "account_kind",
    "person_payload",
    "person_row_fields",
    "unresolved_person_payload",
    "unresolved_person_row_fields",
]


def account_kind(user: UserMirror) -> AccountKind:
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
    }


def person_row_fields(
    user: UserMirror,
    labels: Mapping[str, str],
    prefix: str = "user_",
) -> dict[str, JsonValue]:
    return _row_fields(person_payload(user, labels), prefix)


def unresolved_person_payload(user_id: str) -> dict[str, JsonValue]:
    """成员关系等只存 authentik_user_id、尚无 UserMirror 时的人员形状。

    没有钉钉绑定可观察, 按 `account_kind` 口径视为本地用户; 姓名与部门为空字符串。
    """
    return {
        "user_id": user_id,
        "name": "",
        "department": "",
        "account_kind": ACCOUNT_KIND_LOCAL,
    }


def unresolved_person_row_fields(user_id: str, prefix: str = "user_") -> dict[str, JsonValue]:
    return _row_fields(unresolved_person_payload(user_id), prefix)


def _row_fields(person: Mapping[str, JsonValue], prefix: str) -> dict[str, JsonValue]:
    return {
        f"{prefix}id": person["user_id"],
        f"{prefix}name": person["name"],
        f"{prefix}department": person["department"],
        f"{prefix}account_kind": person["account_kind"],
    }

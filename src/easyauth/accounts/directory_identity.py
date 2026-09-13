"""目录身份判定: 钉钉绑定三元组是否齐备。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from easyauth.accounts.models import UserMirror

__all__ = ["has_directory_identity"]


def has_directory_identity(user: UserMirror) -> bool:
    # 模型约束 accounts_user_dingtalk_binding_shape 保证三字段同空或同非空。
    return bool(user.dingtalk_source_slug and user.dingtalk_corp_id and user.dingtalk_userid)

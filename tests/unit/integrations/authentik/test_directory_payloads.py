from __future__ import annotations

from typing import TYPE_CHECKING

from easyauth.integrations.authentik.directory_payloads import parse_user

if TYPE_CHECKING:
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson


def test_parse_user_passes_through_avatar_and_title() -> None:
    # Given: 上游目录用户携带头像与职位字段。
    payload: DirectoryJson = {
        "corp_id": "corp-1",
        "user_id": "user-1",
        "union_id": "union-1",
        "name": "张三",
        "avatar": "https://static-legacy.dingtalk.com/media/user-1.jpg",
        "title": "销售经理",
        "department_ids": ["dept-1"],
        "manager_userid": "manager-1",
        "status": "active",
    }

    # When: 解析目录用户。
    user = parse_user(payload, source_slug="dingtalk")

    # Then: avatar 与 title 原样透传。
    assert user.avatar == "https://static-legacy.dingtalk.com/media/user-1.jpg"
    assert user.title == "销售经理"


def test_parse_user_defaults_missing_avatar_and_title_to_empty_string() -> None:
    # Given: 上游目录用户缺失头像与职位字段。
    payload: DirectoryJson = {
        "corp_id": "corp-1",
        "user_id": "user-1",
        "status": "active",
    }

    # When: 解析目录用户。
    user = parse_user(payload, source_slug="dingtalk")

    # Then: 缺失字段兜底为空字符串。
    assert user.avatar == ""
    assert user.title == ""

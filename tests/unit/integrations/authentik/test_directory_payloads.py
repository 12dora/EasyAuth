from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from easyauth.integrations.authentik.directory_payloads import (
    parse_departments,
    parse_managed_users,
    parse_user,
    parse_users,
)

if TYPE_CHECKING:
    from easyauth.integrations.authentik.directory_payloads import DirectoryJson


def _managed_users_payload(resolved_at: object) -> dict[str, object]:
    return {
        "source_slug": "dingtalk",
        "corp_id": "corp-1",
        "manager_user_id": "manager-1",
        "resolved_at": resolved_at,
        "users": [],
    }


def test_parse_managed_users_accepts_aware_resolved_at() -> None:
    parsed = parse_managed_users(
        _managed_users_payload("2026-07-02T12:00:00+08:00"),
        source_slug="dingtalk",
    )
    assert parsed.resolved_at == "2026-07-02T12:00:00+08:00"


@pytest.mark.parametrize("resolved_at", ["", "2026-07-02T12:00:00", "not-a-date"])
def test_parse_managed_users_rejects_missing_or_naive_resolved_at(resolved_at: str) -> None:
    # 缺失/naive/非 ISO 的 resolved_at 必须在数据入口就报错(BF-3), 由上层归为目录不可用 -> 503。
    with pytest.raises(ValueError, match=r"resolved_at|empty"):
        _ = parse_managed_users(_managed_users_payload(resolved_at), source_slug="dingtalk")


def test_parse_user_passes_through_profile_and_contact_fields() -> None:
    # Given: 上游目录用户携带展示与联系方式字段。
    payload: DirectoryJson = {
        "corp_id": "corp-1",
        "user_id": "user-1",
        "union_id": "union-1",
        "name": "张三",
        "avatar": "https://static-legacy.dingtalk.com/media/user-1.jpg",
        "title": "销售经理",
        "email": "zhang@example.com",
        "mobile": "13800000001",
        "employee_number": "E0001",
        "department_ids": ["dept-1"],
        "manager_userid": "manager-1",
        "status": "active",
    }

    # When: 解析目录用户。
    user = parse_user(payload, source_slug="dingtalk")

    # Then: 字段原样透传, 不从 UserMirror 或其他来源伪造。
    assert user.avatar == "https://static-legacy.dingtalk.com/media/user-1.jpg"
    assert user.title == "销售经理"
    assert user.email == "zhang@example.com"
    assert user.mobile == "13800000001"
    assert user.employee_number == "E0001"


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
    assert user.email == ""
    assert user.mobile == ""
    assert user.employee_number == ""


@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": {}}])
def test_directory_collection_rejects_missing_or_wrong_results(payload: DirectoryJson) -> None:
    with pytest.raises(TypeError, match="results"):
        _ = parse_departments(payload, source_slug="dingtalk")


def test_directory_collection_accepts_explicit_empty_results() -> None:
    assert parse_departments({"results": []}, source_slug="dingtalk") == ()
    assert parse_users({"results": []}, source_slug="dingtalk") == ()


def test_directory_collection_rejects_non_object_item() -> None:
    with pytest.raises(ValueError, match="identity"):
        _ = parse_users({"results": ["not-an-object"]}, source_slug="dingtalk")

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from easyauth.accounts.directory_references import build_dingtalk_user_ref
from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror, UserMirror
from easyauth.api.directory_payloads import build_user_detail, build_user_list_items

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

_SOURCE = "dingtalk"
_CORP_ID = "corp-demo"
_DEPT_ID = "1"
_MANAGER_USER_ID = "boss-1"
_MANAGER_AUTHENTIK_ID = "auth-boss"
_MISSING_MANAGER_USER_ID = "gone-boss"
_LIST_PAGE_SPECIAL_COUNT = 2
_SMALL_LIST_PAGE_SIZE = 4
_LARGE_LIST_PAGE_SIZE = 20
_LARGE_LIST_REPORT_COUNT = _LARGE_LIST_PAGE_SIZE - _LIST_PAGE_SPECIAL_COUNT
# Authentik 绑定一批 + 部门名称一批 + 主管镜像一批, 与页大小无关。
_USER_LIST_PAYLOAD_QUERIES = 3


def _expected_manager_summary() -> dict[str, JsonValue]:
    return {
        "user_id": _MANAGER_AUTHENTIK_ID,
        "dingtalk_user_id": _MANAGER_USER_ID,
        "source_slug": _SOURCE,
        "corp_id": _CORP_ID,
        "user_ref": build_dingtalk_user_ref(
            source_slug=_SOURCE,
            corp_id=_CORP_ID,
            user_id=_MANAGER_USER_ID,
        ),
        "name": "主管",
        "title": "经理",
        "email": "boss@example.com",
        "mobile": "13800000999",
        "employee_number": "E-BOSS",
        "status": "active",
        "active": True,
    }


def _seed_mixed_manager_page(*, report_count: int) -> list[DingTalkUserMirror]:
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        dept_id=_DEPT_ID,
        name="根",
    )
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        user_id=_MANAGER_USER_ID,
        name="主管",
        title="经理",
        email="boss@example.com",
        mobile="13800000999",
        employee_number="E-BOSS",
        department_ids=[_DEPT_ID],
        manager_userid="",
        status="active",
    )
    _ = UserMirror.objects.create(
        authentik_user_id=_MANAGER_AUTHENTIK_ID,
        name="主管",
        dingtalk_source_slug=_SOURCE,
        dingtalk_corp_id=_CORP_ID,
        dingtalk_userid=_MANAGER_USER_ID,
        status="active",
    )
    no_manager = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        user_id="no-boss",
        name="无主管",
        department_ids=[_DEPT_ID],
        manager_userid="",
        status="active",
    )
    missing_manager = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP_ID,
        user_id="orphan-report",
        name="失踪主管",
        department_ids=[_DEPT_ID],
        manager_userid=_MISSING_MANAGER_USER_ID,
        status="active",
    )
    reports = [
        DingTalkUserMirror.objects.create(
            source_slug=_SOURCE,
            corp_id=_CORP_ID,
            user_id=f"report-{index:03d}",
            name=f"下属{index:03d}",
            department_ids=[_DEPT_ID],
            manager_userid=_MANAGER_USER_ID,
            status="active",
        )
        for index in range(report_count)
    ]
    return [reports[0], no_manager, missing_manager, *reports[1:]]


def test_build_user_list_items_includes_manager_summary_or_null() -> None:
    page = _seed_mixed_manager_page(report_count=_SMALL_LIST_PAGE_SIZE - _LIST_PAGE_SPECIAL_COUNT)
    items = cast("list[dict[str, JsonValue]]", build_user_list_items(page))
    by_id = {item["dingtalk_user_id"]: item for item in items}

    assert by_id["report-000"]["manager"] == _expected_manager_summary()
    assert by_id["no-boss"]["manager"] is None
    assert by_id["orphan-report"]["manager"] is None
    assert build_user_detail(page[0])["manager"] == items[0]["manager"]


def test_build_user_list_items_manager_query_count_is_constant_across_page_size(
    django_assert_num_queries: Callable[[int], AbstractContextManager[object]],
) -> None:
    page = _seed_mixed_manager_page(report_count=_LARGE_LIST_REPORT_COUNT)
    small_page = page[:_SMALL_LIST_PAGE_SIZE]
    large_page = page[:_LARGE_LIST_PAGE_SIZE]

    with CaptureQueriesContext(connection) as small_queries:
        small_items = build_user_list_items(small_page)
    with django_assert_num_queries(_USER_LIST_PAYLOAD_QUERIES):
        large_items = build_user_list_items(large_page)

    small_by_id = {
        item["dingtalk_user_id"]: item for item in cast("list[dict[str, JsonValue]]", small_items)
    }
    large_by_id = {
        item["dingtalk_user_id"]: item for item in cast("list[dict[str, JsonValue]]", large_items)
    }
    last_report_id = f"report-{_LARGE_LIST_REPORT_COUNT - 1:03d}"
    assert len(large_page) == _LARGE_LIST_PAGE_SIZE
    assert len(small_queries) == _USER_LIST_PAYLOAD_QUERIES
    assert small_by_id["report-000"]["manager"] == _expected_manager_summary()
    assert small_by_id["no-boss"]["manager"] is None
    assert small_by_id["orphan-report"]["manager"] is None
    assert large_by_id["report-000"]["manager"] == _expected_manager_summary()
    assert large_by_id["no-boss"]["manager"] is None
    assert large_by_id["orphan-report"]["manager"] is None
    assert large_by_id[last_report_id]["manager"] == _expected_manager_summary()

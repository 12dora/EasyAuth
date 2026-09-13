from __future__ import annotations

import pytest
from django.db.models import Q

from easyauth.accounts.models import UserMirror
from easyauth.accounts.user_search import apply_user_search, user_search_q

pytestmark = pytest.mark.django_db


def test_user_search_q_matches_name_email_id_employee_and_pinyin() -> None:
    query = "hyq"
    expected = (
        Q(name__icontains=query)
        | Q(email__icontains=query)
        | Q(authentik_user_id__icontains=query)
        | Q(employee_number__icontains=query)
    )
    expected |= Q(name_pinyin__icontains=query) | Q(name_pinyin_initials__icontains=query)
    assert user_search_q(query) == expected


def test_user_search_q_prefix_rewrites_related_lookups() -> None:
    query = "胡玉"
    expected = (
        Q(user__name__icontains=query)
        | Q(user__email__icontains=query)
        | Q(user__authentik_user_id__icontains=query)
        | Q(user__employee_number__icontains=query)
    )
    assert user_search_q(query, prefix="user__") == expected


def test_apply_user_search_matches_name_id_and_pinyin_initials() -> None:
    matched = UserMirror.objects.create(
        authentik_user_id="ak-user-search-huyuqin",
        name="胡玉琴A",
        email="huyuqin@example.com",
        employee_number="E-1001",
    )
    _ = UserMirror.objects.create(
        authentik_user_id="ak-user-search-other",
        name="张三",
        email="zhangsan@example.com",
    )

    by_name = apply_user_search(UserMirror.objects.all(), "胡玉")
    by_id = apply_user_search(UserMirror.objects.all(), "search-huyu")
    by_initials = apply_user_search(UserMirror.objects.all(), "hyq")
    by_email = apply_user_search(UserMirror.objects.all(), "huyuqin@")
    by_employee = apply_user_search(UserMirror.objects.all(), "E-1001")

    assert list(by_name) == [matched]
    assert list(by_id) == [matched]
    assert list(by_initials) == [matched]
    assert list(by_email) == [matched]
    assert list(by_employee) == [matched]

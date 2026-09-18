from __future__ import annotations

import pytest
from django.db.models import Q

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.accounts.pinyin import name_pinyin_fields, pinyin_query_filter

pytestmark = pytest.mark.django_db


def test_name_pinyin_fields_keeps_ascii_alnum_on_cjk_name() -> None:
    assert name_pinyin_fields("胡玉琴A") == ("huyuqina", "hyqa")


def test_name_pinyin_fields_skips_spaces_and_punctuation() -> None:
    assert name_pinyin_fields("张 三-") == ("zhangsan", "zs")


def test_name_pinyin_fields_keeps_ascii_letters_and_digits() -> None:
    assert name_pinyin_fields("John2") == ("john2", "john2")


def test_name_pinyin_fields_uses_whole_word_reading_for_heteronyms() -> None:
    assert name_pinyin_fields("重庆") == ("chongqing", "cq")
    assert name_pinyin_fields("长安") == ("changan", "ca")


def test_name_pinyin_fields_keeps_ascii_run_in_full_and_initials() -> None:
    assert name_pinyin_fields("Mike王") == ("mikewang", "mikew")


def test_name_pinyin_fields_empty() -> None:
    assert name_pinyin_fields("") == ("", "")


def test_pinyin_query_filter_matches_ascii_alnum_and_strips_spaces() -> None:
    expected = Q(name_pinyin__icontains="huyu") | Q(name_pinyin_initials__icontains="huyu")
    assert pinyin_query_filter("Hu Yu") == expected


def test_pinyin_query_filter_skips_non_ascii_and_empty() -> None:
    assert pinyin_query_filter("胡玉") is None
    assert pinyin_query_filter("") is None
    assert pinyin_query_filter("  ") is None
    assert pinyin_query_filter("-") is None


def test_pinyin_query_filter_prefix_uses_related_lookups() -> None:
    expected = Q(user__name_pinyin__icontains="hyq") | Q(
        user__name_pinyin_initials__icontains="hyq",
    )
    assert pinyin_query_filter("hyq", prefix="user__") == expected


def test_user_mirror_save_fills_pinyin_when_name_set() -> None:
    user = UserMirror.objects.create(authentik_user_id="ak-pinyin-save", name="胡玉琴A")

    assert user.name_pinyin == "huyuqina"
    assert user.name_pinyin_initials == "hyqa"

    user.name = "张三"
    user.save(update_fields=["name", "updated_at"])
    user.refresh_from_db()

    assert user.name_pinyin == "zhangsan"
    assert user.name_pinyin_initials == "zs"


def test_user_mirror_update_and_bulk_update_fill_pinyin_when_name_written() -> None:
    user = UserMirror.objects.create(authentik_user_id="ak-pinyin-update", name="旧名")

    updated = UserMirror.objects.filter(pk=user.pk).update(name="胡玉琴A")
    user.refresh_from_db()
    assert updated == 1
    assert user.name_pinyin == "huyuqina"
    assert user.name_pinyin_initials == "hyqa"

    user.name = "李四B"
    bulk = UserMirror.objects.bulk_update([user], ["name"])
    user.refresh_from_db()
    assert bulk == 1
    assert user.name_pinyin == "lisib"
    assert user.name_pinyin_initials == "lsb"


def test_dingtalk_user_mirror_save_fills_pinyin_when_name_set() -> None:
    user = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-pinyin-save",
        user_id="user-pinyin-save",
        name="张甜",
    )

    assert user.name_pinyin == "zhangtian"
    assert user.name_pinyin_initials == "zt"

    user.name = "李四"
    user.save(update_fields=["name", "last_synced_at"])
    user.refresh_from_db()

    assert user.name_pinyin == "lisi"
    assert user.name_pinyin_initials == "ls"


def test_dingtalk_user_mirror_update_and_bulk_update_fill_pinyin_when_name_written() -> None:
    user = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-pinyin-update",
        user_id="user-pinyin-update",
        name="旧名",
    )

    updated = DingTalkUserMirror.objects.filter(pk=user.pk).update(name="张甜")
    user.refresh_from_db()
    assert updated == 1
    assert user.name_pinyin == "zhangtian"
    assert user.name_pinyin_initials == "zt"

    user.name = "李四B"
    bulk = DingTalkUserMirror.objects.bulk_update([user], ["name"])
    user.refresh_from_db()
    assert bulk == 1
    assert user.name_pinyin == "lisib"
    assert user.name_pinyin_initials == "lsb"


def test_user_mirror_bulk_create_fills_pinyin_on_insert_and_upsert() -> None:
    created = UserMirror.objects.bulk_create(
        [UserMirror(authentik_user_id="ak-pinyin-bulk-create", name="胡玉琴A")],
    )
    assert len(created) == 1
    created[0].refresh_from_db()
    assert created[0].name_pinyin == "huyuqina"
    assert created[0].name_pinyin_initials == "hyqa"

    _ = UserMirror.objects.bulk_create(
        [UserMirror(authentik_user_id="ak-pinyin-bulk-create", name="李四B")],
        update_conflicts=True,
        update_fields=["name"],
        unique_fields=["authentik_user_id"],
    )
    created[0].refresh_from_db()
    assert created[0].name == "李四B"
    assert created[0].name_pinyin == "lisib"
    assert created[0].name_pinyin_initials == "lsb"


def test_dingtalk_user_mirror_bulk_create_fills_pinyin_on_insert_and_upsert() -> None:
    created = DingTalkUserMirror.objects.bulk_create(
        [
            DingTalkUserMirror(
                source_slug="dingtalk",
                corp_id="corp-pinyin-bulk-create",
                user_id="user-pinyin-bulk-create",
                name="张甜",
            ),
        ],
    )
    assert len(created) == 1
    created[0].refresh_from_db()
    assert created[0].name_pinyin == "zhangtian"
    assert created[0].name_pinyin_initials == "zt"

    _ = DingTalkUserMirror.objects.bulk_create(
        [
            DingTalkUserMirror(
                source_slug="dingtalk",
                corp_id="corp-pinyin-bulk-create",
                user_id="user-pinyin-bulk-create",
                name="李四B",
            ),
        ],
        update_conflicts=True,
        update_fields=["name"],
        unique_fields=["source_slug", "corp_id", "user_id"],
    )
    created[0].refresh_from_db()
    assert created[0].name == "李四B"
    assert created[0].name_pinyin == "lisib"
    assert created[0].name_pinyin_initials == "lsb"

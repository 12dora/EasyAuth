from __future__ import annotations

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.accounts.pinyin import name_pinyin_fields

pytestmark = pytest.mark.django_db


def test_name_pinyin_fields_keeps_ascii_alnum_on_cjk_name() -> None:
    assert name_pinyin_fields("胡玉琴A") == ("huyuqina", "hyqa")


def test_name_pinyin_fields_skips_spaces_and_punctuation() -> None:
    assert name_pinyin_fields("张 三-") == ("zhangsan", "zs")


def test_name_pinyin_fields_keeps_ascii_letters_and_digits() -> None:
    assert name_pinyin_fields("John2") == ("john2", "john2")


def test_name_pinyin_fields_empty() -> None:
    assert name_pinyin_fields("") == ("", "")


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

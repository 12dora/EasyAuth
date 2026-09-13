from __future__ import annotations

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.accounts.person_payload import (
    ACCOUNT_KIND_DIRECTORY,
    ACCOUNT_KIND_LOCAL,
    account_kind,
    person_payload,
    person_row_fields,
    unresolved_person_payload,
    unresolved_person_row_fields,
)

pytestmark = pytest.mark.django_db


def test_account_kind_directory_when_dingtalk_userid_bound() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-directory",
        name="目录用户",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="dt-1",
    )

    assert account_kind(user) == ACCOUNT_KIND_DIRECTORY


def test_account_kind_local_for_authentik_uuid_without_dingtalk() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        name="认证系统管理员",
    )

    assert account_kind(user) == ACCOUNT_KIND_LOCAL


def test_account_kind_local_for_local_admin_subject() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="local-admin:break-glass",
        name="本地管理员",
    )

    assert account_kind(user) == ACCOUNT_KIND_LOCAL


def test_person_payload_uses_batched_department_label() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-labeled",
        name="胡玉琴A",
        department="叶子名",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="dt-labeled",
    )
    labels = {user.authentik_user_id: "捷发-安环部"}

    assert person_payload(user, labels) == {
        "user_id": "ak-labeled",
        "name": "胡玉琴A",
        "department": "捷发-安环部",
        "account_kind": ACCOUNT_KIND_DIRECTORY,
    }


def test_person_payload_falls_back_to_user_department_when_label_missing() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-fallback",
        name="本地用户",
        department="销售部",
    )

    assert person_payload(user, {}) == {
        "user_id": "ak-fallback",
        "name": "本地用户",
        "department": "销售部",
        "account_kind": ACCOUNT_KIND_LOCAL,
    }


def test_person_row_fields_default_prefix() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-row",
        name="胡玉琴A",
        department="安环部",
    )

    assert person_row_fields(user, {}) == {
        "user_id": "ak-row",
        "user_name": "胡玉琴A",
        "user_department": "安环部",
        "user_account_kind": ACCOUNT_KIND_LOCAL,
    }


def test_person_row_fields_originator_prefix() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-originator",
        name="发起人",
        department="研发部",
    )

    assert person_row_fields(user, {}, prefix="originator_") == {
        "originator_id": "ak-originator",
        "originator_name": "发起人",
        "originator_department": "研发部",
        "originator_account_kind": ACCOUNT_KIND_LOCAL,
    }


def test_unresolved_person_payload_is_local_with_empty_display_fields() -> None:
    assert unresolved_person_payload("missing-user") == {
        "user_id": "missing-user",
        "name": "",
        "department": "",
        "account_kind": ACCOUNT_KIND_LOCAL,
    }


def test_unresolved_person_row_fields_uses_user_prefix() -> None:
    assert unresolved_person_row_fields("missing-user") == {
        "user_id": "missing-user",
        "user_name": "",
        "user_department": "",
        "user_account_kind": ACCOUNT_KIND_LOCAL,
    }

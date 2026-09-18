from __future__ import annotations

import pytest

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.accounts.person_payload import (
    ACCOUNT_KIND_DIRECTORY,
    ACCOUNT_KIND_DIRECTORY_UNREGISTERED,
    ACCOUNT_KIND_LOCAL,
    ACCOUNT_KIND_UNRESOLVED,
    account_kind,
    directory_unregistered_person_payload,
    directory_user_triple,
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
        avatar_url="https://static-legacy.dingtalk.com/media/labeled.jpg",
    )
    labels = {user.authentik_user_id: "捷发-安环部"}

    assert person_payload(user, labels) == {
        "user_id": "ak-labeled",
        "name": "胡玉琴A",
        "department": "捷发-安环部",
        "account_kind": ACCOUNT_KIND_DIRECTORY,
        "avatar_url": "https://static-legacy.dingtalk.com/media/labeled.jpg",
    }


def test_person_payload_emits_empty_avatar_url_for_unsafe_stored_value() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-legacy-avatar",
        name="历史头像",
        avatar_url="http://legacy.example/a.png",
    )

    assert person_payload(user, {})["avatar_url"] == ""


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
        "avatar_url": "",
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
        "user_avatar_url": "",
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
        "originator_avatar_url": "",
    }


def test_unresolved_person_payload_is_unresolved_with_empty_display_fields() -> None:
    assert unresolved_person_payload("missing-user") == {
        "user_id": "missing-user",
        "name": "",
        "department": "",
        "account_kind": ACCOUNT_KIND_UNRESOLVED,
        "avatar_url": "",
    }


def test_unresolved_person_row_fields_uses_user_prefix() -> None:
    assert unresolved_person_row_fields("missing-user") == {
        "user_id": "missing-user",
        "user_name": "",
        "user_department": "",
        "user_account_kind": ACCOUNT_KIND_UNRESOLVED,
        "user_avatar_url": "",
    }


def test_app_owner_with_dingtalk_binding_is_directory() -> None:
    owner = UserMirror.objects.create(
        authentik_user_id="ak-owner-directory",
        name="目录负责人",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="dt-owner-1",
    )

    assert person_payload(owner, {})["account_kind"] == ACCOUNT_KIND_DIRECTORY


def test_missing_mirror_owner_is_unresolved() -> None:
    assert unresolved_person_payload("never-logged-in-owner") == {
        "user_id": "never-logged-in-owner",
        "name": "",
        "department": "",
        "account_kind": ACCOUNT_KIND_UNRESOLVED,
        "avatar_url": "",
    }


def test_local_admin_owner_is_local() -> None:
    owner = UserMirror.objects.create(
        authentik_user_id="local-admin:break-glass",
        name="本地管理员",
    )

    assert person_payload(owner, {})["account_kind"] == ACCOUNT_KIND_LOCAL


def test_directory_user_triple_is_null_without_dingtalk_binding() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-local-triple",
        name="本地用户",
    )

    assert directory_user_triple(user) is None


def test_directory_user_triple_emits_bound_identity() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-bound-triple",
        name="目录用户",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="dt-bound",
    )

    assert directory_user_triple(user) == {
        "source_slug": "dingtalk",
        "corp_id": "corp-1",
        "user_id": "dt-bound",
    }


def test_directory_unregistered_person_payload_shape() -> None:
    user = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        user_id="0220123456",
        name="张甜",
        avatar="https://static-legacy.dingtalk.com/media/zhangtian.jpg",
        department_ids=["11"],
    )

    assert directory_unregistered_person_payload(user, "捷发-安环部") == {
        "user_id": None,
        "name": "张甜",
        "department": "捷发-安环部",
        "account_kind": ACCOUNT_KIND_DIRECTORY_UNREGISTERED,
        "avatar_url": "https://static-legacy.dingtalk.com/media/zhangtian.jpg",
        "directory_user": {
            "source_slug": "dingtalk",
            "corp_id": "corp-1",
            "user_id": "0220123456",
        },
    }


def test_directory_unregistered_person_payload_drops_unsafe_avatar() -> None:
    user = DingTalkUserMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        user_id="u-unsafe-avatar",
        name="不安全头像",
        avatar="http://legacy.example/a.png",
    )

    assert directory_unregistered_person_payload(user, "")["avatar_url"] == ""

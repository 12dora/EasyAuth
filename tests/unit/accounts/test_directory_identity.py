from __future__ import annotations

import pytest

from easyauth.accounts.auth import LOCAL_ADMIN_SUBJECT_PREFIX as AUTH_PREFIX
from easyauth.accounts.directory_identity import has_directory_identity
from easyauth.accounts.local_admin import LOCAL_ADMIN_SUBJECT_PREFIX as ADMIN_PREFIX
from easyauth.accounts.models import UserMirror
from easyauth.accounts.person_payload import (
    ACCOUNT_KIND_DIRECTORY,
    ACCOUNT_KIND_LOCAL,
    account_kind,
)

pytestmark = pytest.mark.django_db


def test_local_admin_subject_prefix_is_defined_once() -> None:
    assert AUTH_PREFIX == "local-admin:"
    assert AUTH_PREFIX is ADMIN_PREFIX


def test_has_directory_identity_requires_dingtalk_triple() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-directory",
        name="目录用户",
        dingtalk_source_slug="dingtalk",
        dingtalk_corp_id="corp-1",
        dingtalk_userid="dt-1",
    )

    assert has_directory_identity(user) is True
    assert account_kind(user) == ACCOUNT_KIND_DIRECTORY


def test_has_directory_identity_false_for_authentik_local_user() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        name="认证系统管理员",
    )

    assert has_directory_identity(user) is False
    assert account_kind(user) == ACCOUNT_KIND_LOCAL


def test_has_directory_identity_false_for_local_admin() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="local-admin:break-glass",
        name="本地管理员",
    )

    assert has_directory_identity(user) is False
    assert account_kind(user) == ACCOUNT_KIND_LOCAL

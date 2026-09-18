from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Final, cast

import pytest
from django.contrib.auth.models import User
from django.test import Client

from easyauth.accounts.auth import AUTHENTIK_SESSION_KEY
from easyauth.accounts.models import (
    USER_STATUS_DISABLED,
    DingTalkDepartmentMirror,
    DingTalkUserMirror,
    UserMirror,
)
from tests.integration.admin_console.auth_helpers import authenticate_console_admin

if TYPE_CHECKING:
    from django.http import HttpResponse

    from easyauth.api.errors import JsonValue

pytestmark = pytest.mark.django_db

USER_OPTIONS_API_URL: Final = "/console/api/v1/user-options"
LOGIN_VALUE: Final = "user-options-directory-password"
_SOURCE: Final = "dingtalk"
_CORP: Final = "ding-corp-include-dir"

_OPTION_KEYS: Final = frozenset(
    {"user_id", "name", "department", "avatar_url", "account_kind", "directory_user"},
)


def test_include_directory_omitted_does_not_return_unregistered_people() -> None:
    client = _logged_in_superuser("include-dir-omitted-admin")
    _unregistered(user_id="u-never-login", name="张甜未登录")

    omitted = client.get(USER_OPTIONS_API_URL, {"q": "张甜"})
    explicit_false = client.get(
        USER_OPTIONS_API_URL,
        {"q": "张甜", "include_directory": "false"},
    )

    assert omitted.status_code == HTTPStatus.OK
    assert explicit_false.status_code == HTTPStatus.OK
    assert omitted.json()["data"] == []
    assert explicit_false.json()["data"] == []


def test_include_directory_appends_unregistered_after_user_mirrors() -> None:
    client = _logged_in_superuser("include-dir-order-admin")
    registered = UserMirror.objects.create(
        authentik_user_id="ak-zhang-wei",
        name="张伟已登录",
        dingtalk_source_slug=_SOURCE,
        dingtalk_corp_id=_CORP,
        dingtalk_userid="u-zhang-wei",
        avatar_url="https://static-legacy.dingtalk.com/media/wei.png",
    )
    _unregistered(user_id="u-zhang-wei", name="张伟已登录")
    unregistered = _unregistered(user_id="u-zhang-tian", name="张甜未登录")
    unregistered.avatar = "https://static-legacy.dingtalk.com/media/tian.png"
    unregistered.department_ids = ["11"]
    unregistered.save(update_fields=["avatar", "department_ids", "last_synced_at"])
    _seed_departments()

    response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "张", "include_directory": "true"},
    )

    items = _items(response)
    assert response.status_code == HTTPStatus.OK
    assert [item["name"] for item in items] == ["张伟已登录", "张甜未登录"]
    assert items[0] == {
        "user_id": registered.authentik_user_id,
        "name": "张伟已登录",
        "department": "",
        "account_kind": "directory",
        "avatar_url": "https://static-legacy.dingtalk.com/media/wei.png",
        "directory_user": {
            "source_slug": _SOURCE,
            "corp_id": _CORP,
            "user_id": "u-zhang-wei",
        },
    }
    assert items[1] == {
        "user_id": None,
        "name": "张甜未登录",
        "department": "捷发-安环部",
        "account_kind": "directory_unregistered",
        "avatar_url": "https://static-legacy.dingtalk.com/media/tian.png",
        "directory_user": {
            "source_slug": unregistered.source_slug,
            "corp_id": unregistered.corp_id,
            "user_id": unregistered.user_id,
        },
    }
    assert set(items[0]) == _OPTION_KEYS
    assert set(items[1]) == _OPTION_KEYS


def test_include_directory_local_usermirror_emits_null_directory_user() -> None:
    client = _logged_in_superuser("include-dir-local-admin")
    local = UserMirror.objects.create(
        authentik_user_id="ak-local-option",
        name="本地张三",
        department="销售部",
    )

    response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "张三", "include_directory": "true"},
    )

    items = _items(response)
    assert response.status_code == HTTPStatus.OK
    assert items == [
        {
            "user_id": local.authentik_user_id,
            "name": "本地张三",
            "department": "销售部",
            "account_kind": "local",
            "avatar_url": "",
            "directory_user": None,
        },
    ]


def test_include_directory_matches_name_employee_number_and_userid() -> None:
    client = _logged_in_superuser("include-dir-match-admin")
    by_name = _unregistered(user_id="u-name", name="胡玉琴未登录")
    by_employee = _unregistered(user_id="u-employee", name="工号人员")
    by_employee.employee_number = "E-7788"
    by_employee.save(update_fields=["employee_number", "last_synced_at"])
    by_userid = _unregistered(user_id="0220exactid", name="钉钉号人员")
    extra = _unregistered(user_id="0220exactid-suffix", name="不应按子串命中")
    extra.employee_number = "E-7788-extra"
    extra.save(update_fields=["employee_number", "last_synced_at"])
    emailed = _unregistered(user_id="u-email-only", name="邮箱人员")
    emailed.email = "huyuqin-dir@example.com"
    emailed.save(update_fields=["email", "last_synced_at"])

    name_items = _items(
        client.get(USER_OPTIONS_API_URL, {"q": "胡玉", "include_directory": "true"}),
    )
    employee_items = _items(
        client.get(USER_OPTIONS_API_URL, {"q": "e-7788", "include_directory": "true"}),
    )
    userid_items = _items(
        client.get(
            USER_OPTIONS_API_URL,
            {"q": "0220exactid", "include_directory": "true"},
        ),
    )
    email_items = _items(
        client.get(
            USER_OPTIONS_API_URL,
            {"q": "huyuqin-dir@", "include_directory": "true"},
        ),
    )

    assert [item["directory_user"] for item in name_items] == [_triple(by_name)]
    assert [item["directory_user"] for item in employee_items] == [_triple(by_employee)]
    assert [item["directory_user"] for item in userid_items] == [_triple(by_userid)]
    assert email_items == []


def test_include_directory_excludes_inactive_tombstone_and_registered() -> None:
    client = _logged_in_superuser("include-dir-exclude-admin")
    _unregistered(user_id="u-active", name="在职未登录")
    disabled = _unregistered(user_id="u-disabled", name="停用未登录")
    disabled.status = USER_STATUS_DISABLED
    disabled.save(update_fields=["status", "last_synced_at"])
    tombstone = _unregistered(user_id="u-tombstone", name="墓碑未登录")
    tombstone.is_tombstone = True
    tombstone.save(update_fields=["is_tombstone", "last_synced_at"])
    departed_mirror = UserMirror.objects.create(
        authentik_user_id="ak-departed-dir",
        name="已镜像离职",
        status=USER_STATUS_DISABLED,
        dingtalk_source_slug=_SOURCE,
        dingtalk_corp_id=_CORP,
        dingtalk_userid="u-departed-mirror",
    )
    _unregistered(user_id=departed_mirror.dingtalk_userid, name="已镜像离职")

    response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "未登录", "include_directory": "true"},
    )
    departed = client.get(
        USER_OPTIONS_API_URL,
        {"q": "已镜像离职", "include_directory": "true"},
    )

    items = _items(response)
    assert response.status_code == HTTPStatus.OK
    assert [item["directory_user"] for item in items] == [
        {"source_slug": _SOURCE, "corp_id": _CORP, "user_id": "u-active"},
    ]
    assert departed.status_code == HTTPStatus.OK
    assert departed.json()["data"] == []


def test_include_directory_respects_existing_limit() -> None:
    client = _logged_in_superuser("include-dir-limit-admin")
    first = UserMirror.objects.create(
        authentik_user_id="ak-limit-a",
        name="限额A",
    )
    second = UserMirror.objects.create(
        authentik_user_id="ak-limit-b",
        name="限额B",
    )
    _unregistered(user_id="u-limit-c", name="限额C")

    limit_one = _items(
        client.get(
            USER_OPTIONS_API_URL,
            {"q": "限额", "include_directory": "true", "limit": "1"},
        ),
    )
    limit_two = _items(
        client.get(
            USER_OPTIONS_API_URL,
            {"q": "限额", "include_directory": "true", "limit": "2"},
        ),
    )
    limit_three = _items(
        client.get(
            USER_OPTIONS_API_URL,
            {"q": "限额", "include_directory": "true", "limit": "3"},
        ),
    )

    assert [item["user_id"] for item in limit_one] == [first.authentik_user_id]
    assert [item["name"] for item in limit_two] == [first.name, second.name]
    assert [item["name"] for item in limit_three] == [first.name, second.name, "限额C"]
    assert limit_three[2]["user_id"] is None


@pytest.mark.parametrize("raw_value", ["yes", "TRUE", "1", "True", ""])
def test_include_directory_rejects_invalid_value(raw_value: str) -> None:
    suffix = raw_value.lower() or "empty"
    client = _logged_in_superuser(f"include-dir-invalid-{suffix}-admin")

    response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "张", "include_directory": raw_value},
    )

    error = response.json()["error"]
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert isinstance(error, dict)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == {"field": "include_directory"}
    assert error["message"] == "include_directory 仅支持 true 或 false。"


def test_include_directory_rejects_non_employee_purpose() -> None:
    client = _logged_in_superuser("include-dir-purpose-admin")

    response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "张", "purpose": "approver", "include_directory": "true"},
    )

    error = response.json()["error"]
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert isinstance(error, dict)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == {"field": "include_directory"}
    assert error["message"] == "include_directory 仅允许与 purpose=employee 同时使用。"


def test_include_directory_rejects_user_ids_lookup() -> None:
    client = _logged_in_superuser("include-dir-lookup-admin")
    person = UserMirror.objects.create(
        authentik_user_id="ak-lookup-dir",
        name="回填用户",
    )

    response = client.get(
        USER_OPTIONS_API_URL,
        {
            "user_ids": person.authentik_user_id,
            "include_directory": "true",
        },
    )

    error = response.json()["error"]
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert isinstance(error, dict)
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == {"field": "include_directory"}
    assert error["message"] == "include_directory 不能与 user_ids 同时使用。"


def test_include_directory_false_keeps_lookup_shape() -> None:
    client = _logged_in_superuser("include-dir-lookup-false-admin")
    person = UserMirror.objects.create(
        authentik_user_id="ak-lookup-false",
        name="回填用户",
        department="销售部",
    )

    response = client.get(
        USER_OPTIONS_API_URL,
        {
            "user_ids": person.authentik_user_id,
            "include_directory": "false",
        },
    )

    items = _items(response)
    assert response.status_code == HTTPStatus.OK
    assert items == [
        {
            "user_id": person.authentik_user_id,
            "name": "回填用户",
            "department": "销售部",
            "account_kind": "local",
            "avatar_url": "",
        },
    ]
    assert set(items[0]) == {
        "user_id",
        "name",
        "department",
        "avatar_url",
        "account_kind",
    }


def test_include_directory_forbidden_for_non_superuser() -> None:
    client = _logged_in_console_user("include-dir-ordinary")

    response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "张", "include_directory": "true"},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    error = response.json()["error"]
    assert isinstance(error, dict)
    assert error["code"] == "PERMISSION_DENIED"


def test_include_directory_pinyin_matches_unregistered() -> None:
    client = _logged_in_superuser("include-dir-pinyin-admin")
    person = _unregistered(user_id="u-pinyin", name="张甜")

    full_response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "zhangtian", "include_directory": "true"},
    )
    prefix_response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "zhang", "include_directory": "true"},
    )
    initials_response = client.get(
        USER_OPTIONS_API_URL,
        {"q": "zt", "include_directory": "true"},
    )

    assert full_response.status_code == HTTPStatus.OK
    assert prefix_response.status_code == HTTPStatus.OK
    assert initials_response.status_code == HTTPStatus.OK
    assert [item["directory_user"] for item in _items(full_response)] == [_triple(person)]
    assert [item["directory_user"] for item in _items(prefix_response)] == [_triple(person)]
    assert [item["directory_user"] for item in _items(initials_response)] == [_triple(person)]


def _items(response: HttpResponse) -> list[dict[str, JsonValue]]:
    payload: dict[str, JsonValue] = cast(
        "dict[str, JsonValue]",
        json.loads(response.content.decode()),
    )
    return cast("list[dict[str, JsonValue]]", payload["data"])


def _triple(user: DingTalkUserMirror) -> dict[str, str]:
    return {
        "source_slug": user.source_slug,
        "corp_id": user.corp_id,
        "user_id": user.user_id,
    }


def _unregistered(*, user_id: str, name: str) -> DingTalkUserMirror:
    return DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id=user_id,
        name=name,
    )


def _seed_departments() -> None:
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        dept_id="1",
        parent_id="",
        name="",
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        dept_id="10",
        parent_id="1",
        name="捷发",
    )
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        dept_id="11",
        parent_id="10",
        name="安环部",
    )


def _logged_in_console_user(username: str) -> Client:
    _ = UserMirror.objects.create(authentik_user_id=username)
    client = Client(HTTP_HOST="localhost")
    session = client.session
    session[AUTHENTIK_SESSION_KEY] = username
    session.save()
    return client


def _logged_in_superuser(username: str) -> Client:
    _ = User.objects.create_superuser(username=username, password=LOGIN_VALUE)
    client = Client(HTTP_HOST="localhost")
    authenticate_console_admin(client, username)
    return client

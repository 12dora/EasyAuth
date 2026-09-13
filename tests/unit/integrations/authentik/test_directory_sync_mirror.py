from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from easyauth.accounts.models import UserMirror
from easyauth.integrations.authentik.directory_sync_mirror import _sync_user_mirror_avatars

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from easyauth.integrations.authentik.directory_payloads import DirectoryJson

pytestmark = pytest.mark.django_db

_AVATAR_STEP_QUERIES = 2
_SMALL_SNAPSHOT_USERS = 3
_LARGE_SNAPSHOT_USERS = 6
_DIRECTORY_AVATAR = "https://static-legacy.dingtalk.com/media/directory.jpg"
_EXISTING_AVATAR = "https://oidc.example.test/media/original.jpg"
_UNSAFE_AVATAR = "data:image/svg+xml;base64,PHN2Zy4uLg=="


def test_sync_user_mirror_avatars_updates_only_changed_bound_rows() -> None:
    backfill = _bound_user(ak_id="ak-backfill", user_id="user-backfill")
    overwrite = _bound_user(
        ak_id="ak-overwrite",
        user_id="user-overwrite",
        avatar_url=_EXISTING_AVATAR,
    )
    unchanged = _bound_user(
        ak_id="ak-unchanged",
        user_id="user-unchanged",
        avatar_url=_DIRECTORY_AVATAR,
    )
    empty_dir = _bound_user(
        ak_id="ak-empty-dir",
        user_id="user-empty-dir",
        avatar_url=_EXISTING_AVATAR,
    )
    unsafe_dir = _bound_user(
        ak_id="ak-unsafe-dir",
        user_id="user-unsafe-dir",
        avatar_url=_EXISTING_AVATAR,
    )
    other_source = _bound_user(
        ak_id="ak-other-source",
        user_id="user-backfill",
        source_slug="other-source",
        avatar_url="",
    )
    unbound = UserMirror.objects.create(
        authentik_user_id="ak-unbound",
        avatar_url=_EXISTING_AVATAR,
    )
    outsider = _bound_user(
        ak_id="ak-outsider",
        user_id="user-outsider",
        avatar_url=_EXISTING_AVATAR,
    )

    _sync_user_mirror_avatars(
        [
            _payload(user_id="user-backfill", avatar=_DIRECTORY_AVATAR),
            _payload(user_id="user-overwrite", avatar=_DIRECTORY_AVATAR),
            _payload(user_id="user-unchanged", avatar=_DIRECTORY_AVATAR),
            _payload(user_id="user-empty-dir", avatar=""),
            _payload(user_id="user-unsafe-dir", avatar=_UNSAFE_AVATAR),
            _payload(user_id="user-unbound-dir", avatar=_DIRECTORY_AVATAR),
        ],
    )

    backfill.refresh_from_db()
    overwrite.refresh_from_db()
    unchanged.refresh_from_db()
    empty_dir.refresh_from_db()
    unsafe_dir.refresh_from_db()
    other_source.refresh_from_db()
    unbound.refresh_from_db()
    outsider.refresh_from_db()
    assert backfill.avatar_url == _DIRECTORY_AVATAR
    assert overwrite.avatar_url == _DIRECTORY_AVATAR
    assert unchanged.avatar_url == _DIRECTORY_AVATAR
    assert empty_dir.avatar_url == _EXISTING_AVATAR
    assert unsafe_dir.avatar_url == _EXISTING_AVATAR
    assert other_source.avatar_url == ""
    assert unbound.avatar_url == _EXISTING_AVATAR
    assert outsider.avatar_url == _EXISTING_AVATAR
    assert not UserMirror.objects.filter(dingtalk_userid="user-unbound-dir").exists()


def test_sync_user_mirror_avatars_skips_queries_when_directory_has_no_safe_avatar(
    django_assert_num_queries: Callable[[int], AbstractContextManager[object]],
) -> None:
    user = _bound_user(
        ak_id="ak-no-safe-avatar",
        user_id="user-no-safe-avatar",
        avatar_url=_EXISTING_AVATAR,
    )

    with django_assert_num_queries(0):
        _sync_user_mirror_avatars(
            [
                _payload(user_id="user-no-safe-avatar", avatar=""),
                _payload(user_id="user-no-safe-avatar-2", avatar=_UNSAFE_AVATAR),
            ],
        )

    user.refresh_from_db()
    assert user.avatar_url == _EXISTING_AVATAR


def test_sync_user_mirror_avatars_query_count_is_constant_for_snapshot(
    django_assert_num_queries: Callable[[int], AbstractContextManager[object]],
) -> None:
    small_payloads = _stale_avatar_snapshot(count=_SMALL_SNAPSHOT_USERS, prefix="small")
    large_payloads = _stale_avatar_snapshot(count=_LARGE_SNAPSHOT_USERS, prefix="large")

    with CaptureQueriesContext(connection) as small_queries:
        _sync_user_mirror_avatars(small_payloads)
    with django_assert_num_queries(len(small_queries)):
        _sync_user_mirror_avatars(large_payloads)

    assert len(small_queries) == _AVATAR_STEP_QUERIES
    assert len(small_payloads) >= 3
    for index in range(_SMALL_SNAPSHOT_USERS):
        small = UserMirror.objects.get(authentik_user_id=f"ak-small-{index}")
        assert small.avatar_url == f"https://static-legacy.dingtalk.com/media/small-{index}.jpg"
    for index in range(_LARGE_SNAPSHOT_USERS):
        large = UserMirror.objects.get(authentik_user_id=f"ak-large-{index}")
        assert large.avatar_url == f"https://static-legacy.dingtalk.com/media/large-{index}.jpg"


def _stale_avatar_snapshot(*, count: int, prefix: str) -> list[DirectoryJson]:
    payloads: list[DirectoryJson] = []
    for index in range(count):
        user_id = f"{prefix}-user-{index}"
        avatar = f"https://static-legacy.dingtalk.com/media/{prefix}-{index}.jpg"
        _ = _bound_user(
            ak_id=f"ak-{prefix}-{index}",
            user_id=user_id,
            avatar_url=_EXISTING_AVATAR,
        )
        payloads.append(_payload(user_id=user_id, avatar=avatar))
    return payloads


def _bound_user(
    *,
    ak_id: str,
    user_id: str,
    avatar_url: str = "",
    source_slug: str = "dingtalk",
    corp_id: str = "corp-1",
) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=ak_id,
        dingtalk_source_slug=source_slug,
        dingtalk_corp_id=corp_id,
        dingtalk_userid=user_id,
        avatar_url=avatar_url,
    )


def _payload(
    *,
    user_id: str,
    avatar: str,
    source_slug: str = "dingtalk",
    corp_id: str = "corp-1",
) -> DirectoryJson:
    return {
        "source_slug": source_slug,
        "corp_id": corp_id,
        "user_id": user_id,
        "avatar": avatar,
    }

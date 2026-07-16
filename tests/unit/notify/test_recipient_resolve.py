from __future__ import annotations

import pytest

from easyauth.accounts.models import DingTalkUserMirror, UserMirror
from easyauth.notify.models import (
    NOTIFY_ERROR_NO_DINGTALK_ID,
    NOTIFY_ERROR_USER_INACTIVE,
    NOTIFY_ERROR_USER_NOT_FOUND,
    NOTIFY_RECIPIENT_STATUS_FAILED,
    NOTIFY_RECIPIENT_STATUS_PENDING,
)
from easyauth.notify.services import NotifyAcceptError, resolve_recipients

pytestmark = pytest.mark.django_db

CORP_ID = "corp-test"
SOURCE = "dingtalk-primary"


def _dt_user(
    *,
    user_id: str,
    status: str = "active",
    corp_id: str = CORP_ID,
) -> DingTalkUserMirror:
    return DingTalkUserMirror.objects.create(
        source_slug=SOURCE,
        corp_id=corp_id,
        user_id=user_id,
        name=user_id,
        status=status,
    )


def _user_mirror(
    *,
    authentik_user_id: str,
    dingtalk_userid: str = "",
    corp_id: str = CORP_ID,
) -> UserMirror:
    return UserMirror.objects.create(
        authentik_user_id=authentik_user_id,
        dingtalk_userid=dingtalk_userid,
        dingtalk_corp_id=corp_id if dingtalk_userid else "",
        name=authentik_user_id,
    )


def test_resolve_bare_user_id_active() -> None:
    _ = _dt_user(user_id="dt-alice")
    _ = _user_mirror(authentik_user_id="auth-alice", dingtalk_userid="dt-alice")

    resolved = resolve_recipients(["auth-alice"])

    assert len(resolved) == 1
    item = resolved[0]
    assert item.raw_ref == "auth-alice"
    assert item.dingtalk_userid == "dt-alice"
    assert item.status == NOTIFY_RECIPIENT_STATUS_PENDING
    assert item.error_code == ""
    assert item.user is not None
    assert item.user.authentik_user_id == "auth-alice"


def test_resolve_dt_prefix_without_login() -> None:
    _ = _dt_user(user_id="dt-newbie")

    resolved = resolve_recipients(["dt:dt-newbie"])

    assert len(resolved) == 1
    item = resolved[0]
    assert item.raw_ref == "dt:dt-newbie"
    assert item.dingtalk_userid == "dt-newbie"
    assert item.user is None
    assert item.status == NOTIFY_RECIPIENT_STATUS_PENDING


def test_resolve_merges_same_person_by_dingtalk_userid() -> None:
    _ = _dt_user(user_id="dt-bob")
    _ = _user_mirror(authentik_user_id="auth-bob", dingtalk_userid="dt-bob")

    resolved = resolve_recipients(["auth-bob", "dt:dt-bob", "auth-bob"])

    assert len(resolved) == 1
    assert resolved[0].raw_ref == "auth-bob"
    assert resolved[0].dingtalk_userid == "dt-bob"


def test_resolve_unknown_ref_is_failed_not_blocking() -> None:
    resolved = resolve_recipients(["ghost-user", "dt:missing-person"])

    expected_count = 2
    assert len(resolved) == expected_count
    assert all(item.status == NOTIFY_RECIPIENT_STATUS_FAILED for item in resolved)
    assert all(item.error_code == NOTIFY_ERROR_USER_NOT_FOUND for item in resolved)


def test_resolve_no_dingtalk_binding() -> None:
    _ = _user_mirror(authentik_user_id="auth-nobind", dingtalk_userid="")

    resolved = resolve_recipients(["auth-nobind"])

    assert len(resolved) == 1
    assert resolved[0].status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert resolved[0].error_code == NOTIFY_ERROR_NO_DINGTALK_ID


def test_resolve_departed_user_is_inactive() -> None:
    _ = _dt_user(user_id="dt-gone", status="departed")
    _ = _user_mirror(authentik_user_id="auth-gone", dingtalk_userid="dt-gone")

    resolved = resolve_recipients(["auth-gone"])

    assert len(resolved) == 1
    assert resolved[0].status == NOTIFY_RECIPIENT_STATUS_FAILED
    assert resolved[0].error_code == NOTIFY_ERROR_USER_INACTIVE
    assert "departed" in resolved[0].error


def test_resolve_dt_prefix_inactive() -> None:
    _ = _dt_user(user_id="dt-disabled", status="disabled")

    resolved = resolve_recipients(["dt:dt-disabled"])

    assert resolved[0].error_code == NOTIFY_ERROR_USER_INACTIVE
    assert resolved[0].dingtalk_userid == "dt-disabled"


def test_resolve_rejects_empty_or_out_of_range() -> None:
    with pytest.raises(NotifyAcceptError, match="1~500") as exc:
        _ = resolve_recipients([])
    assert exc.value.kind == "validation_error"
    assert exc.value.field == "recipients"

    with pytest.raises(NotifyAcceptError, match="1~500"):
        _ = resolve_recipients([f"u{i}" for i in range(501)])

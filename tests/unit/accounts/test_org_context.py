from __future__ import annotations

from easyauth.accounts.models import UserMirror
from easyauth.accounts.org_context import apply_dingtalk_org_context


def _user() -> UserMirror:
    return UserMirror(authentik_user_id="ak-user")


def test_empty_authentik_org_context_does_not_write_partial_binding() -> None:
    user = _user()

    changed = apply_dingtalk_org_context(
        user,
        {
            "corp_id": None,
            "user_id": None,
            "source_slug": "dingtalk",
            "departments": [],
            "manager": None,
            "manager_chain": [],
            "stale": True,
            "last_synced_at": None,
        },
    )

    assert changed == []
    assert user.dingtalk_source_slug == ""
    assert user.dingtalk_corp_id == ""
    assert user.dingtalk_userid == ""
    assert user.department == ""
    assert user.manager_userid == ""


def test_partial_org_identity_does_not_write_binding_or_department() -> None:
    user = _user()
    user.department = "原部门"

    changed = apply_dingtalk_org_context(
        user,
        {
            "source_slug": "dingtalk",
            "corp_id": "ding-corp",
            "user_id": "",
            "departments": [{"name": "销售部"}],
            "manager": {"user_id": "ding-manager"},
        },
    )

    assert changed == []
    assert user.dingtalk_source_slug == ""
    assert user.dingtalk_corp_id == ""
    assert user.dingtalk_userid == ""
    assert user.department == "原部门"


def test_complete_org_context_updates_binding_and_department() -> None:
    user = _user()

    changed = apply_dingtalk_org_context(
        user,
        {
            "source_slug": "dingtalk",
            "corp_id": "ding-corp",
            "user_id": "ding-user",
            "departments": [{"dept_id": "2", "name": "销售部"}],
            "manager": {"user_id": "ding-manager", "name": "李经理"},
        },
    )

    assert changed == [
        "dingtalk_source_slug",
        "dingtalk_corp_id",
        "dingtalk_userid",
        "department",
        "manager_userid",
    ]
    assert user.dingtalk_source_slug == "dingtalk"
    assert user.dingtalk_corp_id == "ding-corp"
    assert user.dingtalk_userid == "ding-user"
    assert user.department == "销售部"
    assert user.manager_userid == "ding-manager"


def test_missing_org_context_does_not_rewrite_fields() -> None:
    user = _user()
    user.dingtalk_source_slug = "dingtalk"
    user.dingtalk_corp_id = "ding-corp"
    user.dingtalk_userid = "ding-user"
    user.department = "销售部"

    assert apply_dingtalk_org_context(user, None) == []
    assert apply_dingtalk_org_context(user, "dingtalk") == []
    assert user.dingtalk_source_slug == "dingtalk"
    assert user.department == "销售部"

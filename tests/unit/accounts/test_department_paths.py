from __future__ import annotations

import pytest

from easyauth.accounts.department_paths import (
    department_path_labels,
    directory_department_path_labels,
)
from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror, UserMirror

pytestmark = pytest.mark.django_db

_SOURCE = "dingtalk"
_CORP = "corp-1"


def test_department_path_skips_empty_root_name() -> None:
    _dept("1", "", "")
    _dept("135693208", "1", "捷发")
    _dept("137485443", "135693208", "IT维护")
    user = _bound_user("ak-it", "u-it", ["137485443"])

    labels = department_path_labels((user,))

    assert labels[user.authentik_user_id] == "捷发-IT维护"


def test_department_path_joins_multiple_departments_in_mirror_order() -> None:
    _dept("1", "", "")
    _dept("10", "1", "捷发")
    _dept("11", "10", "安环部")
    _dept("12", "10", "IT维护")
    user = _bound_user("ak-multi", "u-multi", ["11", "12"])

    labels = department_path_labels((user,))

    assert labels[user.authentik_user_id] == "捷发-安环部 / 捷发-IT维护"


def test_department_path_falls_back_when_dingtalk_mirror_missing() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ak-local",
        name="本地用户",
        department="销售部",
    )

    labels = department_path_labels((user,))

    assert labels[user.authentik_user_id] == "销售部"


def test_department_path_falls_back_when_department_ids_empty() -> None:
    _dept("1", "", "")
    user = _bound_user("ak-empty-depts", "u-empty-depts", [])
    user.department = "叶子部门"
    user.save(update_fields=["department", "updated_at"])

    labels = department_path_labels((user,))

    assert labels[user.authentik_user_id] == "叶子部门"


def test_department_path_is_cycle_safe() -> None:
    _dept("a", "b", "甲")
    _dept("b", "a", "乙")
    user = _bound_user("ak-cycle", "u-cycle", ["a"])

    labels = department_path_labels((user,))

    assert labels[user.authentik_user_id] == "乙-甲"


def test_department_path_missing_parent_keeps_known_names() -> None:
    _dept("100", "missing", "叶子")
    user = _bound_user("ak-missing-parent", "u-missing-parent", ["100"])

    labels = department_path_labels((user,))

    assert labels[user.authentik_user_id] == "叶子"


def test_directory_department_path_labels_match_usermirror_helper() -> None:
    _dept("1", "", "")
    _dept("10", "1", "捷发")
    _dept("11", "10", "安环部")
    user = _bound_user("ak-dir-label", "u-dir-label", ["11"])
    dt_user = DingTalkUserMirror.objects.get(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id="u-dir-label",
    )

    labels = directory_department_path_labels((dt_user,))

    assert labels[(_SOURCE, _CORP, "u-dir-label")] == "捷发-安环部"
    assert (
        labels[(_SOURCE, _CORP, "u-dir-label")]
        == department_path_labels((user,))[user.authentik_user_id]
    )


def test_directory_department_path_labels_omits_empty_departments() -> None:
    dt_user = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id="u-no-dept",
        name="无部门",
        department_ids=[],
    )

    assert directory_department_path_labels((dt_user,)) == {}


def _dept(dept_id: str, parent_id: str, name: str) -> None:
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        dept_id=dept_id,
        parent_id=parent_id,
        name=name,
    )


def _bound_user(
    authentik_user_id: str,
    dingtalk_userid: str,
    department_ids: list[str],
) -> UserMirror:
    user = UserMirror.objects.create(
        authentik_user_id=authentik_user_id,
        name=authentik_user_id,
        department="叶子名",
        dingtalk_source_slug=_SOURCE,
        dingtalk_corp_id=_CORP,
        dingtalk_userid=dingtalk_userid,
    )
    _ = DingTalkUserMirror.objects.create(
        source_slug=_SOURCE,
        corp_id=_CORP,
        user_id=dingtalk_userid,
        name=authentik_user_id,
        department_ids=department_ids,
    )
    return user

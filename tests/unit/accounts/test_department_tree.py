from __future__ import annotations

import pytest

from easyauth.accounts.department_tree import DepartmentTree, DepartmentTreeCycleError
from easyauth.accounts.models import DingTalkDepartmentMirror

pytestmark = pytest.mark.django_db


def _dept(dept_id: str, parent_id: str, name: str, order: int = 0) -> None:
    _ = DingTalkDepartmentMirror.objects.create(
        source_slug="dingtalk",
        corp_id="corp-1",
        dept_id=dept_id,
        parent_id=parent_id,
        name=name,
        order=order,
    )


def test_department_tree_ancestors_subtree_and_path() -> None:
    _dept("1", "", "公司")
    _dept("10", "1", "销售部", order=2)
    _dept("11", "1", "研发部", order=1)
    _dept("100", "10", "华东销售")

    tree = DepartmentTree.load(source_slug="dingtalk", corp_id="corp-1")

    assert tree.root_ids() == ("1",)
    assert tree.children_of("1") == ("11", "10")
    assert tree.ancestors_or_self("100") == ("100", "10", "1")
    assert tree.ancestors_or_self_for(["100", "11"]) == frozenset({"100", "10", "1", "11"})
    assert tree.subtree_ids("10") == ("10", "100")
    assert [node.name for node in tree.path("100")] == ["公司", "销售部", "华东销售"]


def test_department_tree_unknown_department_only_returns_itself() -> None:
    _dept("1", "", "公司")
    tree = DepartmentTree.load(source_slug="dingtalk", corp_id="corp-1")

    assert tree.ancestors_or_self("999") == ("999",)
    assert tree.path("999") == ()


def test_department_tree_cycle_fails_fast() -> None:
    _dept("1", "2", "甲")
    _dept("2", "1", "乙")
    tree = DepartmentTree.load(source_slug="dingtalk", corp_id="corp-1")

    with pytest.raises(DepartmentTreeCycleError):
        _ = tree.ancestors_or_self("1")

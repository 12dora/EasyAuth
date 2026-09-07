from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast, final

from easyauth.accounts.models import DingTalkDepartmentMirror

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["DepartmentNode", "DepartmentTree", "DepartmentTreeCycleError"]


class DepartmentTreeCycleError(RuntimeError):
    """部门镜像的 parent_id 形成环, 目录数据不可信, 必须快速失败。"""


@dataclass(frozen=True, slots=True)
class DepartmentNode:
    dept_id: str
    parent_id: str
    name: str
    order: int


@final
@dataclass(slots=True)
class DepartmentTree:
    """某个 (source_slug, corp_id) 下的钉钉部门树, 一次加载后在内存里做祖先/子树计算。"""

    source_slug: str
    corp_id: str
    nodes: dict[str, DepartmentNode]
    _children: dict[str, tuple[str, ...]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        children: dict[str, list[str]] = {}
        for node in self.nodes.values():
            children.setdefault(node.parent_id, []).append(node.dept_id)
        self._children = {
            parent_id: tuple(
                sorted(
                    ids,
                    key=lambda dept_id: (
                        self.nodes[dept_id].order,
                        self.nodes[dept_id].name,
                        dept_id,
                    ),
                ),
            )
            for parent_id, ids in children.items()
        }

    @classmethod
    def load(cls, *, source_slug: str, corp_id: str) -> DepartmentTree:
        rows = cast(
            "Iterable[tuple[str, str, str, int]]",
            DingTalkDepartmentMirror.objects.filter(
                source_slug=source_slug,
                corp_id=corp_id,
            ).values_list("dept_id", "parent_id", "name", "order"),
        )
        nodes = {
            dept_id: DepartmentNode(dept_id=dept_id, parent_id=parent_id, name=name, order=order)
            for dept_id, parent_id, name, order in rows
        }
        return cls(source_slug=source_slug, corp_id=corp_id, nodes=nodes)

    def root_ids(self) -> tuple[str, ...]:
        return tuple(dept_id for dept_id in self._children.get("", ())) + tuple(
            dept_id
            for dept_id, node in sorted(self.nodes.items())
            if node.parent_id != "" and node.parent_id not in self.nodes
        )

    def children_of(self, dept_id: str) -> tuple[str, ...]:
        return self._children.get(dept_id, ())

    def ancestors_or_self(self, dept_id: str) -> tuple[str, ...]:
        """从自身到根的部门 ID 链; 未知部门返回仅含自身的链(镜像滞后时策略只按已知祖先生效)。"""
        chain: list[str] = [dept_id]
        seen = {dept_id}
        current = self.nodes.get(dept_id)
        while current is not None and current.parent_id != "":
            parent_id = current.parent_id
            if parent_id in seen:
                message = f"department parent chain has a cycle at {parent_id}"
                raise DepartmentTreeCycleError(message)
            seen.add(parent_id)
            chain.append(parent_id)
            current = self.nodes.get(parent_id)
        return tuple(chain)

    def ancestors_or_self_for(self, dept_ids: Iterable[str]) -> frozenset[str]:
        result: set[str] = set()
        for dept_id in dept_ids:
            result.update(self.ancestors_or_self(dept_id))
        return frozenset(result)

    def subtree_ids(self, dept_id: str) -> tuple[str, ...]:
        """含自身的子树 ID(广度优先)。"""
        result: list[str] = []
        queue: deque[str] = deque([dept_id])
        seen: set[str] = set()
        while queue:
            current = queue.popleft()
            if current in seen:
                message = f"department tree has a cycle at {current}"
                raise DepartmentTreeCycleError(message)
            seen.add(current)
            result.append(current)
            queue.extend(self.children_of(current))
        return tuple(result)

    def path(self, dept_id: str) -> tuple[DepartmentNode, ...]:
        """从根到自身的节点路径(只包含镜像中存在的节点)。"""
        return tuple(
            self.nodes[item]
            for item in reversed(self.ancestors_or_self(dept_id))
            if item in self.nodes
        )

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.db.models import Q

from easyauth.accounts.models import DingTalkDepartmentMirror, DingTalkUserMirror

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.accounts.models import UserMirror

__all__ = ["department_path_labels"]

_PATH_JOIN: Final = "-"
_MULTI_PATH_JOIN: Final = " / "
type _CorpKey = tuple[str, str]
type _UserKey = tuple[str, str, str]
type _DeptNode = tuple[str, str]


def department_path_labels(users: Iterable[UserMirror]) -> dict[str, str]:
    """批量解析用户部门路径标签, 键为 authentik_user_id。

    钉钉部门链从最上有名祖先到叶子, 以 "-" 连接, 跳过空名(公司根 dept_id=1
    的 name 为空)。多部门按 DingTalkUserMirror.department_ids 顺序以 " / "
    拼接。无钉钉镜像或无部门时回退到 UserMirror.department。
    """
    user_list = tuple(users)
    labels = {user.authentik_user_id: user.department for user in user_list}
    bindings = _dingtalk_bindings(user_list)
    if not bindings:
        return labels

    dt_users = _dingtalk_users(bindings)
    trees = _department_trees(dt_users.values())
    for user, key in bindings:
        dt_user = dt_users.get(key)
        if dt_user is None:
            continue
        dept_ids = _department_ids(dt_user.department_ids)
        if not dept_ids:
            continue
        nodes = trees.get((key[0], key[1]), {})
        paths = [path for dept_id in dept_ids if (path := _path_label(dept_id, nodes))]
        if paths:
            labels[user.authentik_user_id] = _MULTI_PATH_JOIN.join(paths)
    return labels


def _dingtalk_bindings(users: tuple[UserMirror, ...]) -> list[tuple[UserMirror, _UserKey]]:
    bindings: list[tuple[UserMirror, _UserKey]] = []
    for user in users:
        source_slug = user.dingtalk_source_slug
        corp_id = user.dingtalk_corp_id
        userid = user.dingtalk_userid
        if source_slug == "" or corp_id == "" or userid == "":
            continue
        bindings.append((user, (source_slug, corp_id, userid)))
    return bindings


def _dingtalk_users(
    bindings: list[tuple[UserMirror, _UserKey]],
) -> dict[_UserKey, DingTalkUserMirror]:
    query = Q()
    seen: set[_UserKey] = set()
    for _user, key in bindings:
        if key in seen:
            continue
        seen.add(key)
        source_slug, corp_id, userid = key
        query |= Q(source_slug=source_slug, corp_id=corp_id, user_id=userid)
    rows = DingTalkUserMirror.objects.filter(query).only(
        "source_slug",
        "corp_id",
        "user_id",
        "department_ids",
    )
    return {(row.source_slug, row.corp_id, row.user_id): row for row in rows}


def _department_trees(
    dt_users: Iterable[DingTalkUserMirror],
) -> dict[_CorpKey, dict[str, _DeptNode]]:
    query = Q()
    seen: set[_CorpKey] = set()
    for row in dt_users:
        if not _department_ids(row.department_ids):
            continue
        key = (row.source_slug, row.corp_id)
        if key in seen:
            continue
        seen.add(key)
        query |= Q(source_slug=row.source_slug, corp_id=row.corp_id)
    if not seen:
        return {}
    trees: dict[_CorpKey, dict[str, _DeptNode]] = {}
    for row in DingTalkDepartmentMirror.objects.filter(query).only(
        "source_slug",
        "corp_id",
        "dept_id",
        "parent_id",
        "name",
    ):
        trees.setdefault((row.source_slug, row.corp_id), {})[row.dept_id] = (
            row.parent_id,
            row.name,
        )
    return trees


def _department_ids(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in cast("list[object]", raw) if isinstance(item, str) and item)


def _path_label(dept_id: str, nodes: dict[str, _DeptNode]) -> str:
    names: list[str] = []
    seen: set[str] = set()
    current = dept_id
    while current and current not in seen:
        seen.add(current)
        node = nodes.get(current)
        if node is None:
            break
        parent_id, name = node
        if name:
            names.append(name)
        current = parent_id
    names.reverse()
    return _PATH_JOIN.join(names)

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from django.db.models import Q
from django.utils import timezone

from easyauth.accounts.models import UserMirror
from easyauth.api.datetime_json import datetime_value
from easyauth.api.errors import JsonValue
from easyauth.applications.models import AppScope
from easyauth.grants.department_policies import (
    CorpMembershipIndex,
    DirectoryCorp,
    direct_member_count,
    eligible_user_count,
)
from easyauth.grants.models import DepartmentGrantPolicy

if TYPE_CHECKING:
    from collections.abc import Iterable

    from easyauth.accounts.department_tree import DepartmentTree
    from easyauth.applications.models import AuthorizationGroup, Permission
    from easyauth.grants.models import DepartmentGrantPolicyGroup, DepartmentGrantPolicyPermission

type JsonObject = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class PolicyViewContext:
    tree: DepartmentTree
    viewing_dept_id: str
    memberships: CorpMembershipIndex
    scope_names: dict[tuple[int, str], str]
    actors: dict[str, UserMirror]


def serialize_department_tree(
    *,
    corp: DirectoryCorp,
    tree: DepartmentTree,
    memberships: CorpMembershipIndex,
) -> JsonObject:
    roots = tree.root_ids()
    primary = roots[0]
    extra_roots = roots[1:]
    return {
        "source_slug": corp.source_slug,
        "corp_id": corp.corp_id,
        "synced_at": datetime_value(corp.synced_at),
        "root": _tree_node(
            tree,
            primary,
            memberships=memberships,
            extra_children=extra_roots,
        ),
    }


def serialize_department_summary(
    *,
    tree: DepartmentTree,
    dept_id: str,
    memberships: CorpMembershipIndex,
) -> JsonObject:
    node = tree.nodes[dept_id]
    subtree = frozenset(tree.subtree_ids(dept_id))
    path_items: list[JsonValue] = [
        {"dept_id": item.dept_id, "name": item.name} for item in tree.path(dept_id)
    ]
    return {
        "dept_id": node.dept_id,
        "name": node.name,
        "path": path_items,
        "member_count": direct_member_count(memberships, dept_id),
        "subtree_member_count": eligible_user_count(memberships, subtree),
    }


def build_policy_view_context(
    *,
    tree: DepartmentTree,
    viewing_dept_id: str,
    memberships: CorpMembershipIndex,
    policies: tuple[DepartmentGrantPolicy, ...],
) -> PolicyViewContext:
    app_ids = {policy.app_id for policy in policies}
    actor_ids = {policy.created_by_id for policy in policies} | {
        policy.updated_by_id for policy in policies
    }
    scope_rows = cast(
        "Iterable[tuple[int, str, str]]",
        AppScope.objects.filter(app_id__in=app_ids).values_list("app_id", "key", "name"),
    )
    scope_names = {(app_id, key): name for app_id, key, name in scope_rows}
    actors = {
        user.authentik_user_id: user
        for user in UserMirror.objects.filter(authentik_user_id__in=actor_ids)
    }
    return PolicyViewContext(
        tree=tree,
        viewing_dept_id=viewing_dept_id,
        memberships=memberships,
        scope_names=scope_names,
        actors=actors,
    )


def sort_policies_for_department(
    policies: tuple[DepartmentGrantPolicy, ...],
    *,
    tree: DepartmentTree,
    dept_id: str,
) -> tuple[DepartmentGrantPolicy, ...]:
    ancestors = tree.ancestors_or_self(dept_id)
    level_by_dept = {ancestor: index for index, ancestor in enumerate(ancestors)}
    visible = tuple(
        policy
        for policy in policies
        if policy.dept_id in tree.nodes and policy.dept_id in level_by_dept
    )
    return tuple(
        sorted(
            visible,
            key=lambda policy: (
                level_by_dept[policy.dept_id],
                policy.app.alias.strip() or policy.app.name,
                policy.app.name,
                policy.id,
            ),
        ),
    )


def effective_policies(
    *,
    source_slug: str,
    corp_id: str,
    dept_ids: tuple[str, ...],
) -> tuple[DepartmentGrantPolicy, ...]:
    now = timezone.now()
    queryset = (
        DepartmentGrantPolicy.objects.select_related("app")
        .prefetch_related("policy_groups__authorization_group", "policy_permissions__permission")
        .filter(source_slug=source_slug, corp_id=corp_id, dept_id__in=dept_ids)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
    )
    return tuple(queryset)


def serialize_policy_item(policy: DepartmentGrantPolicy, context: PolicyViewContext) -> JsonObject:
    defined_node = context.tree.nodes[policy.dept_id]
    subtree = frozenset(context.tree.subtree_ids(policy.dept_id))
    groups: list[JsonValue] = [
        _group_item(link.authorization_group) for link in _policy_groups(policy)
    ]
    permissions: list[JsonValue] = [
        _permission_item(link.permission, link.scope_key, context.scope_names, policy.app_id)
        for link in _policy_permissions(policy)
    ]
    return {
        "id": policy.id,
        "app": {
            "app_key": policy.app.app_key,
            "name": policy.app.name,
            "alias": policy.app.alias,
        },
        "authorization_groups": groups,
        "permissions": permissions,
        "grant_type": policy.grant_type,
        "expires_at": datetime_value(policy.expires_at),
        "reason": policy.reason,
        "defined_on": {"dept_id": defined_node.dept_id, "name": defined_node.name},
        "inherited": policy.dept_id != context.viewing_dept_id,
        "affected_user_count": eligible_user_count(context.memberships, subtree),
        "created_at": datetime_value(policy.created_at),
        "updated_at": datetime_value(policy.updated_at),
        "created_by": _actor_item(policy.created_by_id, context.actors),
        "updated_by": _actor_item(policy.updated_by_id, context.actors),
    }


def _tree_node(
    tree: DepartmentTree,
    dept_id: str,
    *,
    memberships: CorpMembershipIndex,
    extra_children: tuple[str, ...] = (),
) -> JsonObject:
    node = tree.nodes[dept_id]
    child_ids = tuple(tree.children_of(dept_id)) + extra_children
    children: list[JsonValue] = [
        _tree_node(tree, child_id, memberships=memberships) for child_id in child_ids
    ]
    return {
        "dept_id": node.dept_id,
        "name": node.name,
        "member_count": direct_member_count(memberships, dept_id),
        "children": children,
    }


def _group_item(group: AuthorizationGroup) -> JsonObject:
    return {"key": group.key, "name": group.name, "kind": group.kind}


def _permission_item(
    permission: Permission,
    scope_key: str,
    scope_names: dict[tuple[int, str], str],
    app_id: int,
) -> JsonObject:
    return {
        "key": permission.key,
        "name": permission.name,
        "scope": scope_key,
        "scope_name": scope_names[(app_id, scope_key)],
    }


def _actor_item(user_id: str, actors: dict[str, UserMirror]) -> JsonObject:
    actor = actors.get(user_id)
    return {"user_id": user_id, "name": "" if actor is None else actor.name}


def _policy_groups(policy: DepartmentGrantPolicy) -> tuple[DepartmentGrantPolicyGroup, ...]:
    return tuple(
        cast(
            "Iterable[DepartmentGrantPolicyGroup]",
            policy.policy_groups.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        ),
    )


def _policy_permissions(
    policy: DepartmentGrantPolicy,
) -> tuple[DepartmentGrantPolicyPermission, ...]:
    return tuple(
        cast(
            "Iterable[DepartmentGrantPolicyPermission]",
            policy.policy_permissions.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        ),
    )

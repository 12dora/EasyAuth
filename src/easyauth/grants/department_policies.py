from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

from django.db import transaction

from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    DingTalkDepartmentMirror,
    DingTalkDirectorySyncState,
    DingTalkUserMirror,
    UserMirror,
)
from easyauth.api.datetime_json import datetime_value
from easyauth.audit.services import AuditRecord, AuditService
from easyauth.grants.department_reconcile import schedule_department_grant_reconcile
from easyauth.grants.models import (
    DepartmentGrantPolicy,
    DepartmentGrantPolicyGroup,
    DepartmentGrantPolicyPermission,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.api.errors import JsonValue
    from easyauth.applications.models import App, AuthorizationGroup

DIRECTORY_NOT_SYNCED_MESSAGE = "尚未同步钉钉组织架构。"
MULTIPLE_CORPS_MESSAGE = "当前存在多个钉钉企业,组织授权暂不支持多企业目录。"
DIRECTORY_DEPT_SHAPE_MESSAGE = "钉钉用户部门列表必须是字符串数组。"
POLICY_APP_LOCKED_MESSAGE = "组织授权的应用不能修改。"
ACTOR_TYPE_ADMIN = "admin"
POLICY_CREATED_ACTION = "department_policy_created"
POLICY_UPDATED_ACTION = "department_policy_updated"
POLICY_DELETED_ACTION = "department_policy_deleted"
POLICY_TARGET_TYPE = "department_policy"


@dataclass(frozen=True, slots=True)
class DirectoryNotSyncedError(Exception):
    message: str = DIRECTORY_NOT_SYNCED_MESSAGE

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class MultipleDirectoryCorpsError(Exception):
    message: str = MULTIPLE_CORPS_MESSAGE

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class DirectoryDataError(Exception):
    message: str = DIRECTORY_DEPT_SHAPE_MESSAGE

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class DepartmentPolicyImmutableError(Exception):
    message: str = POLICY_APP_LOCKED_MESSAGE

    @override
    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class DirectoryCorp:
    source_slug: str
    corp_id: str
    synced_at: datetime


@dataclass(frozen=True, slots=True)
class CorpMembershipIndex:
    eligible_user_ids_by_dept: dict[str, frozenset[str]]
    direct_member_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class DepartmentPolicyWrite:
    source_slug: str
    corp_id: str
    dept_id: str
    app: App
    authorization_groups: tuple[AuthorizationGroup, ...]
    direct_grants: tuple[ScopedAccessRequestGrant, ...]
    grant_type: str
    expires_at: datetime | None
    reason: str
    actor_id: str


def resolve_single_directory_corp() -> DirectoryCorp:
    sync_corps = cast(
        "set[tuple[str, str]]",
        set(DingTalkDirectorySyncState.objects.values_list("source_slug", "corp_id")),
    )
    dept_corps = cast(
        "set[tuple[str, str]]",
        set(DingTalkDepartmentMirror.objects.values_list("source_slug", "corp_id")),
    )
    if not dept_corps:
        raise DirectoryNotSyncedError
    corps = sync_corps | dept_corps
    if len(corps) > 1:
        raise MultipleDirectoryCorpsError
    source_slug, corp_id = next(iter(corps))
    return DirectoryCorp(
        source_slug=source_slug,
        corp_id=corp_id,
        synced_at=_synced_at(source_slug=source_slug, corp_id=corp_id),
    )


def load_corp_membership_index(*, source_slug: str, corp_id: str) -> CorpMembershipIndex:
    ding_rows = cast(
        "Iterable[tuple[str, object]]",
        DingTalkUserMirror.objects.filter(
            source_slug=source_slug,
            corp_id=corp_id,
            status=USER_STATUS_ACTIVE,
            is_tombstone=False,
        ).values_list("user_id", "department_ids"),
    )
    memberships = tuple((user_id, _string_dept_ids(raw_ids)) for user_id, raw_ids in ding_rows)
    if not memberships:
        return CorpMembershipIndex(eligible_user_ids_by_dept={}, direct_member_counts={})
    eligible = frozenset(
        UserMirror.objects.filter(
            status=USER_STATUS_ACTIVE,
            dingtalk_source_slug=source_slug,
            dingtalk_corp_id=corp_id,
            dingtalk_userid__in=tuple(user_id for user_id, _ in memberships),
        ).values_list("dingtalk_userid", flat=True),
    )
    eligible_user_ids_by_dept: dict[str, set[str]] = {}
    direct_member_counts: dict[str, int] = {}
    for user_id, dept_ids in memberships:
        is_eligible = user_id in eligible
        for dept_id in dept_ids:
            direct_member_counts[dept_id] = direct_member_counts.get(dept_id, 0) + 1
            if is_eligible:
                eligible_user_ids_by_dept.setdefault(dept_id, set()).add(user_id)
    return CorpMembershipIndex(
        eligible_user_ids_by_dept={
            dept_id: frozenset(user_ids) for dept_id, user_ids in eligible_user_ids_by_dept.items()
        },
        direct_member_counts=direct_member_counts,
    )


def direct_member_count(index: CorpMembershipIndex, dept_id: str) -> int:
    return index.direct_member_counts.get(dept_id, 0)


def eligible_user_ids_in_depts(
    index: CorpMembershipIndex, dept_ids: Iterable[str]
) -> frozenset[str]:
    users: set[str] = set()
    for dept_id in dept_ids:
        members = index.eligible_user_ids_by_dept.get(dept_id)
        if members is not None:
            users.update(members)
    return frozenset(users)


def eligible_user_count(index: CorpMembershipIndex, dept_ids: Iterable[str]) -> int:
    return len(eligible_user_ids_in_depts(index, dept_ids))


def create_department_grant_policy(write: DepartmentPolicyWrite) -> DepartmentGrantPolicy:
    with transaction.atomic():
        policy = DepartmentGrantPolicy(
            source_slug=write.source_slug,
            corp_id=write.corp_id,
            dept_id=write.dept_id,
            app=write.app,
            grant_type=write.grant_type,
            expires_at=write.expires_at,
            reason=write.reason,
            created_by_type=ACTOR_TYPE_ADMIN,
            created_by_id=write.actor_id,
            updated_by_type=ACTOR_TYPE_ADMIN,
            updated_by_id=write.actor_id,
        )
        policy.full_clean()
        policy.save()
        _replace_policy_targets(policy, write)
        _record_policy_event(policy, action=POLICY_CREATED_ACTION, write=write)
        schedule_department_grant_reconcile(trigger="policy")
        return policy


def update_department_grant_policy(
    policy: DepartmentGrantPolicy,
    write: DepartmentPolicyWrite,
) -> DepartmentGrantPolicy:
    if policy.app_id != write.app.id:
        raise DepartmentPolicyImmutableError
    with transaction.atomic():
        policy.grant_type = write.grant_type
        policy.expires_at = write.expires_at
        policy.reason = write.reason
        policy.updated_by_type = ACTOR_TYPE_ADMIN
        policy.updated_by_id = write.actor_id
        policy.full_clean()
        policy.save(
            update_fields=[
                "grant_type",
                "expires_at",
                "reason",
                "updated_by_type",
                "updated_by_id",
                "updated_at",
            ],
        )
        _replace_policy_targets(policy, write)
        _record_policy_event(policy, action=POLICY_UPDATED_ACTION, write=write)
        schedule_department_grant_reconcile(trigger="policy")
        return policy


def delete_department_grant_policy(*, policy: DepartmentGrantPolicy, actor_id: str) -> None:
    write = DepartmentPolicyWrite(
        source_slug=policy.source_slug,
        corp_id=policy.corp_id,
        dept_id=policy.dept_id,
        app=policy.app,
        authorization_groups=tuple(
            link.authorization_group for link in _policy_group_links(policy)
        ),
        direct_grants=tuple(
            ScopedAccessRequestGrant(permission=link.permission, scope_key=link.scope_key)
            for link in _policy_permission_links(policy)
        ),
        grant_type=policy.grant_type,
        expires_at=policy.expires_at,
        reason=policy.reason,
        actor_id=actor_id,
    )
    with transaction.atomic():
        _record_policy_event(policy, action=POLICY_DELETED_ACTION, write=write)
        _ = policy.delete()
        schedule_department_grant_reconcile(trigger="policy")


def _replace_policy_targets(policy: DepartmentGrantPolicy, write: DepartmentPolicyWrite) -> None:
    _ = DepartmentGrantPolicyGroup.objects.filter(policy=policy).delete()
    _ = DepartmentGrantPolicyPermission.objects.filter(policy=policy).delete()
    for group in write.authorization_groups:
        link = DepartmentGrantPolicyGroup(policy=policy, authorization_group=group)
        link.full_clean()
        link.save()
    for item in write.direct_grants:
        link = DepartmentGrantPolicyPermission(
            policy=policy,
            permission=item.permission,
            scope_key=item.scope_key,
        )
        link.full_clean()
        link.save()


def _record_policy_event(
    policy: DepartmentGrantPolicy,
    *,
    action: str,
    write: DepartmentPolicyWrite,
) -> None:
    metadata: dict[str, JsonValue] = {
        "source_slug": write.source_slug,
        "corp_id": write.corp_id,
        "dept_id": write.dept_id,
        "app_key": write.app.app_key,
        "authorization_group_keys": [group.key for group in write.authorization_groups],
        "permission_keys": [item.permission.key for item in write.direct_grants],
        "grant_type": write.grant_type,
        "expires_at": datetime_value(write.expires_at),
        "reason": write.reason,
    }
    _ = AuditService.record(
        AuditRecord(
            actor_type=ACTOR_TYPE_ADMIN,
            actor_id=write.actor_id,
            action=action,
            target_type=POLICY_TARGET_TYPE,
            target_id=str(policy.id),
            metadata=metadata,
        ),
    )


def _synced_at(*, source_slug: str, corp_id: str) -> datetime:
    state = DingTalkDirectorySyncState.objects.filter(
        source_slug=source_slug,
        corp_id=corp_id,
    ).first()
    if state is not None:
        return state.last_synced_at
    synced_at = cast(
        "datetime | None",
        DingTalkDepartmentMirror.objects.filter(source_slug=source_slug, corp_id=corp_id)
        .order_by("-last_synced_at")
        .values_list("last_synced_at", flat=True)
        .first(),
    )
    if synced_at is None:
        raise DirectoryNotSyncedError
    return synced_at


def _string_dept_ids(raw_ids: object) -> frozenset[str]:
    if not isinstance(raw_ids, list):
        raise DirectoryDataError
    items = cast("list[object]", raw_ids)
    dept_ids = [item for item in items if isinstance(item, str)]
    if len(dept_ids) != len(items):
        raise DirectoryDataError
    return frozenset(dept_ids)


def _policy_group_links(policy: DepartmentGrantPolicy) -> tuple[DepartmentGrantPolicyGroup, ...]:
    return tuple(
        cast(
            "Iterable[DepartmentGrantPolicyGroup]",
            policy.policy_groups.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        ),
    )


def _policy_permission_links(
    policy: DepartmentGrantPolicy,
) -> tuple[DepartmentGrantPolicyPermission, ...]:
    return tuple(
        cast(
            "Iterable[DepartmentGrantPolicyPermission]",
            policy.policy_permissions.all(),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
        ),
    )

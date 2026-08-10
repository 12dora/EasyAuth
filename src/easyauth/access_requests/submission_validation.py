from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils import timezone

from easyauth.access_requests.submission_types import (
    AccessRequestGrantType,
    AccessRequestSubmission,
    AccessRequestSubmissionError,
    AccessRequestType,
    ScopedAccessRequestGrant,
)
from easyauth.access_requests.target_validation import (
    AccessRequestTargetValidationError,
    validate_request_targets,
)
from easyauth.accounts.models import USER_STATUS_ACTIVE, UserMirror
from easyauth.applications.models import AuthorizationGroupGrant
from easyauth.grants.effective_snapshot import (
    EffectiveGrantSnapshot,
    current_effective_grant_snapshot,
)
from easyauth.grants.models import AccessGrant

MANAGED_USERS_SCOPE = "MANAGED_USERS"
MANAGED_USERS_APPROVER_REQUIRED_MESSAGE = (
    "MANAGED_USERS requests require a direct manager approver."
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from easyauth.applications.models import App, AuthorizationGroup


def validated_request_type(request_type: str) -> AccessRequestType:
    match request_type:
        case "grant" | "change" | "revoke" | "renew":
            return request_type
        case _:
            raise AccessRequestSubmissionError(("unsupported request type",))


def unique_authorization_groups(
    authorization_groups: Iterable[AuthorizationGroup],
) -> tuple[AuthorizationGroup, ...]:
    group_by_id: dict[int, AuthorizationGroup] = {}
    for group in authorization_groups:
        group_by_id[group.id] = group
    return tuple(group_by_id.values())


def unique_direct_grants(
    direct_grants: Iterable[ScopedAccessRequestGrant],
) -> tuple[ScopedAccessRequestGrant, ...]:
    grant_by_identity: dict[tuple[int, str], ScopedAccessRequestGrant] = {}
    for grant in direct_grants:
        grant_by_identity[(grant.permission.id, grant.scope_key)] = grant
    return tuple(grant_by_identity.values())


def validated_approver_user_ids(
    approver_user_ids: Iterable[str],
    *,
    applicant_user_id: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    user_ids = _unique_non_empty_strings(approver_user_ids)
    if not user_ids:
        # ADR-002 §36: 主管链耗尽时允许空审批人, 路由进 superuser_pool。
        if allow_empty:
            return ()
        raise AccessRequestSubmissionError(("at least one approver is required",))

    # 审批人可由申请人自选是设计, 但绝不能是申请人本人: 自审自批会绕过整条审批链。
    # 服务端是权威闸门, 前端过滤只是体验, 这里必须快速失败而非静默剔除。
    if applicant_user_id in user_ids:
        raise AccessRequestSubmissionError(("approver must not be the applicant",))

    active_user_ids = set(
        UserMirror.objects.filter(
            authentik_user_id__in=user_ids,
            status=USER_STATUS_ACTIVE,
        ).values_list("authentik_user_id", flat=True),
    )
    invalid_user_ids = tuple(user_id for user_id in user_ids if user_id not in active_user_ids)
    if invalid_user_ids:
        invalid = ", ".join(invalid_user_ids)
        raise AccessRequestSubmissionError((f"approver must be an active system user: {invalid}",))
    return user_ids


def validate_submission_scope(
    input_data: AccessRequestSubmission,
    request_type: AccessRequestType,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
    *,
    lock_base_grant: bool = False,
) -> None:
    _validate_user(input_data.user)
    _validate_expiration_shape(input_data.grant_type, input_data.grant_expires_at)
    _validate_app(input_data.app)

    match request_type:
        case "grant":
            _validate_no_base_grant(input_data)
            _validate_no_current_grant(input_data.user, input_data.app)
            _validate_targets_present(authorization_groups, direct_grants)
            _validate_targets(input_data.app, authorization_groups, direct_grants)
            _validate_managed_users_approver(input_data, authorization_groups, direct_grants)
        case "change":
            _ = base_lifecycle_grant_snapshot(input_data, for_update=lock_base_grant)
            _validate_targets_present(authorization_groups, direct_grants)
            _validate_targets(input_data.app, authorization_groups, direct_grants)
            _validate_managed_users_approver(input_data, authorization_groups, direct_grants)
        case "revoke":
            snapshot = base_lifecycle_grant_snapshot(input_data, for_update=lock_base_grant)
            _validate_targets_belong_to_app(input_data.app, authorization_groups, direct_grants)
            _validate_revoke_subset(snapshot, authorization_groups, direct_grants)
            _validate_managed_users_approver(input_data, authorization_groups, direct_grants)
        case "renew":
            snapshot = base_lifecycle_grant_snapshot(input_data, for_update=lock_base_grant)
            _validate_renew_request(input_data.grant_type, input_data.grant_expires_at, snapshot)
            _validate_targets_belong_to_app(input_data.app, authorization_groups, direct_grants)
            _validate_renew_targets(snapshot, authorization_groups, direct_grants)
            _validate_managed_users_approver(input_data, authorization_groups, direct_grants)


def _unique_non_empty_strings(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized == "" or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _validate_user(user: UserMirror) -> None:
    match user.status:
        case "active":
            return
        case _:
            raise AccessRequestSubmissionError(("user is not active",))


def _validate_expiration_shape(
    grant_type: AccessRequestGrantType,
    grant_expires_at: datetime | None,
) -> None:
    match grant_type:
        case "permanent":
            if grant_expires_at is not None:
                raise AccessRequestSubmissionError(
                    ("Permanent requests must not include an expiration",),
                )
        case "timed":
            if grant_expires_at is None:
                raise AccessRequestSubmissionError(
                    ("Timed requests must include an expiration",),
                )
            if grant_expires_at <= timezone.now():
                raise AccessRequestSubmissionError(
                    ("Timed requests must expire in the future",),
                )


def _validate_app(app: App) -> None:
    if not app.is_active:
        raise AccessRequestSubmissionError(("app is not active",))


def _validate_targets_present(
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    if not authorization_groups and not direct_grants:
        raise AccessRequestSubmissionError(
            ("at least one authorization group or direct grant is required",),
        )


def _validate_managed_users_approver(
    input_data: AccessRequestSubmission,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    """ADR-002 §36 修订: 审批人沿 manager_chain 向上取, 无可用主管时允许提交进超管池。

    仍然禁止手动改填任意用户绕过主管链。
    """
    if not _contains_managed_users_target(authorization_groups, direct_grants):
        return
    chain_ids = _active_manager_chain_user_ids(input_data.user)
    submitted = _unique_non_empty_strings(input_data.approver_user_ids)
    if chain_ids:
        # 必须恰好是链上第一个可用主管(逐级向上的首个 active)
        if submitted == (chain_ids[0],):
            return
        raise AccessRequestSubmissionError((MANAGED_USERS_APPROVER_REQUIRED_MESSAGE,))
    # 链耗尽: 允许提交且无审批人 / 或空审批人 → 路由进超管池(由 services 落库)
    if not submitted:
        return
    raise AccessRequestSubmissionError((MANAGED_USERS_APPROVER_REQUIRED_MESSAGE,))


def active_manager_chain_user_ids(user: UserMirror) -> tuple[str, ...]:
    """沿 manager_chain 取第一个可用主管; 链不可用时回退 manager_userid 直属字段。"""
    from easyauth.lifecycle.assignee import resolve_assignee

    resolution = resolve_assignee(user, start_level=0)
    if resolution.user is not None:
        return (resolution.user.authentik_user_id,)
    # 回退: 部分同步路径只写 manager_userid、尚未有完整 manager_chain 行。
    manager_userid = (user.manager_userid or "").strip()
    if not manager_userid:
        return ()
    manager = UserMirror.objects.filter(
        authentik_user_id=manager_userid,
        status=USER_STATUS_ACTIVE,
    ).first()
    if manager is None and user.dingtalk_source_slug and user.dingtalk_corp_id:
        manager = UserMirror.objects.filter(
            dingtalk_source_slug=user.dingtalk_source_slug,
            dingtalk_corp_id=user.dingtalk_corp_id,
            dingtalk_userid=manager_userid,
            status=USER_STATUS_ACTIVE,
        ).first()
    if manager is None:
        return ()
    return (manager.authentik_user_id,)


# 兼容内部调用名
_active_manager_chain_user_ids = active_manager_chain_user_ids


def _active_direct_manager_user_id(user: UserMirror) -> str | None:
    ids = active_manager_chain_user_ids(user)
    return ids[0] if ids else None


def contains_managed_users_target(
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> bool:
    if any(grant.scope_key == MANAGED_USERS_SCOPE for grant in direct_grants):
        return True
    group_ids = tuple(group.id for group in authorization_groups)
    if not group_ids:
        return False
    return AuthorizationGroupGrant.objects.filter(
        authorization_group_id__in=group_ids,
        is_active=True,
        scope_key=MANAGED_USERS_SCOPE,
    ).exists()


_contains_managed_users_target = contains_managed_users_target


def _validate_no_current_grant(user: UserMirror, app: App) -> None:
    # grant 请求落地时会插入 is_current=True 的新行; 已有 current 授权必须在提交阶段拒绝,
    # 否则审批通过后才撞 grants_access_grant_one_current 唯一约束, 白白消耗一次审批。
    if AccessGrant.objects.filter(user=user, app=app, is_current=True).exists():
        raise AccessRequestSubmissionError(
            ("current grant already exists, submit a change request instead",),
        )


def _validate_no_base_grant(input_data: AccessRequestSubmission) -> None:
    if input_data.base_grant_id is not None or input_data.base_grant_revision is not None:
        raise AccessRequestSubmissionError(("grant request must not include a base grant",))


def base_lifecycle_grant_snapshot(
    input_data: AccessRequestSubmission,
    *,
    for_update: bool = False,
) -> EffectiveGrantSnapshot:
    if input_data.base_grant_id is None or input_data.base_grant_revision is None:
        raise AccessRequestSubmissionError(("base grant revision is required",))
    snapshot = current_effective_grant_snapshot(
        user=input_data.user,
        app=input_data.app,
        for_update=for_update,
    )
    if snapshot is None:
        raise AccessRequestSubmissionError(("active grant is required",))
    if not snapshot.has_membership():
        raise AccessRequestSubmissionError(("active grant is required",))
    if (
        snapshot.grant.id != input_data.base_grant_id
        or snapshot.grant.version != input_data.base_grant_revision
    ):
        raise AccessRequestSubmissionError(("base grant revision conflict",))
    return snapshot


def _validate_renew_request(
    grant_type: AccessRequestGrantType,
    grant_expires_at: datetime | None,
    snapshot: EffectiveGrantSnapshot,
) -> None:
    match grant_type:
        case "timed":
            current_expirations = snapshot.membership_expirations
            if (
                grant_expires_at is None
                or not current_expirations
                or any(expiration is None for expiration in current_expirations)
            ):
                raise AccessRequestSubmissionError(("renew requires a timed grant expiration",))
            if any(
                grant_expires_at <= expiration
                for expiration in current_expirations
                if expiration is not None
            ):
                raise AccessRequestSubmissionError(("renew expiration must extend current grant",))
        case "permanent":
            raise AccessRequestSubmissionError(("renew requires a timed grant",))


def _validate_revoke_subset(
    snapshot: EffectiveGrantSnapshot,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    current_group_ids = set(snapshot.group_ids)
    target_group_ids = {group.id for group in authorization_groups}
    if not target_group_ids.issubset(current_group_ids):
        raise AccessRequestSubmissionError(("target groups must be subset of current grant",))

    current_direct_grants = set(snapshot.direct_grants)
    target_direct_grants = _target_direct_grants(direct_grants)
    if not target_direct_grants.issubset(current_direct_grants):
        raise AccessRequestSubmissionError(
            ("target direct grants must be subset of current grant",),
        )
    if target_group_ids == current_group_ids and target_direct_grants == current_direct_grants:
        raise AccessRequestSubmissionError(("revoke request must reduce current grant",))


def _validate_renew_targets(
    snapshot: EffectiveGrantSnapshot,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    if {group.id for group in authorization_groups} != set(snapshot.group_ids):
        raise AccessRequestSubmissionError(("renew request must keep current groups",))
    if _target_direct_grants(direct_grants) != set(snapshot.direct_grants):
        raise AccessRequestSubmissionError(("renew request must keep current direct grants",))


def _target_direct_grants(
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> set[tuple[int, str]]:
    return {(grant.permission.id, grant.scope_key) for grant in direct_grants}


def _validate_targets_belong_to_app(
    app: App,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    errors: list[str] = []
    errors.extend(
        f"{group.key}: Authorization group must belong to the access request app."
        for group in authorization_groups
        if group.app_id != app.id
    )
    errors.extend(
        f"{grant.permission.key}: Permission must belong to the access request app."
        for grant in direct_grants
        if grant.permission.app_id != app.id
    )
    if errors:
        raise AccessRequestSubmissionError(tuple(errors))


def _validate_targets(
    app: App,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    try:
        validate_request_targets(app, authorization_groups, direct_grants)
    except AccessRequestTargetValidationError as exc:
        raise AccessRequestSubmissionError(exc.messages) from exc

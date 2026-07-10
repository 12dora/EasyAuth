from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Q
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
from easyauth.grants.models import GRANT_STATUS_ACTIVE as GRANT_RECORD_STATUS_ACTIVE
from easyauth.grants.models import AccessGrant, AccessGrantGroup, AccessGrantPermission

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
) -> tuple[str, ...]:
    user_ids = _unique_non_empty_strings(approver_user_ids)
    if not user_ids:
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
) -> None:
    _validate_user(input_data.user)
    _validate_expiration_shape(input_data.grant_type, input_data.grant_expires_at)
    _validate_app(input_data.app)

    match request_type:
        case "grant":
            _validate_no_current_grant(input_data.user, input_data.app)
            _validate_targets_present(authorization_groups, direct_grants)
            _validate_targets(input_data.app, authorization_groups, direct_grants)
            _validate_managed_users_approver(input_data, authorization_groups, direct_grants)
        case "change":
            _ = _active_lifecycle_grant(input_data.user, input_data.app)
            _validate_targets_present(authorization_groups, direct_grants)
            _validate_targets(input_data.app, authorization_groups, direct_grants)
            _validate_managed_users_approver(input_data, authorization_groups, direct_grants)
        case "revoke":
            grant = _active_lifecycle_grant(input_data.user, input_data.app)
            _validate_targets_belong_to_app(input_data.app, authorization_groups, direct_grants)
            _validate_revoke_subset(grant, authorization_groups, direct_grants)
            _validate_managed_users_approver(input_data, authorization_groups, direct_grants)
        case "renew":
            grant = _active_lifecycle_grant(input_data.user, input_data.app)
            _validate_renew_request(input_data.grant_type, input_data.grant_expires_at, grant)
            _validate_targets_belong_to_app(input_data.app, authorization_groups, direct_grants)
            _validate_renew_targets(grant, authorization_groups, direct_grants)
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
    if not _contains_managed_users_target(authorization_groups, direct_grants):
        return
    manager_user_id = _active_direct_manager_user_id(input_data.user)
    if manager_user_id is not None and _unique_non_empty_strings(
        input_data.approver_user_ids,
    ) == (manager_user_id,):
        return
    raise AccessRequestSubmissionError((MANAGED_USERS_APPROVER_REQUIRED_MESSAGE,))


def _active_direct_manager_user_id(user: UserMirror) -> str | None:
    manager_userid = user.manager_userid.strip()
    if not manager_userid:
        return None
    manager = UserMirror.objects.filter(
        authentik_user_id=manager_userid,
        status=USER_STATUS_ACTIVE,
    ).first()
    if manager is None:
        manager = UserMirror.objects.filter(
            dingtalk_userid=manager_userid,
            status=USER_STATUS_ACTIVE,
        ).first()
    return manager.authentik_user_id if manager is not None else None


def _contains_managed_users_target(
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


def _validate_no_current_grant(user: UserMirror, app: App) -> None:
    # grant 请求落地时会插入 is_current=True 的新行; 已有 current 授权必须在提交阶段拒绝,
    # 否则审批通过后才撞 grants_access_grant_one_current 唯一约束, 白白消耗一次审批。
    if AccessGrant.objects.filter(user=user, app=app, is_current=True).exists():
        raise AccessRequestSubmissionError(
            ("current grant already exists, submit a change request instead",),
        )


def _active_lifecycle_grant(user: UserMirror, app: App) -> AccessGrant:
    grant = AccessGrant.objects.filter(
        user=user,
        app=app,
        is_current=True,
        status=GRANT_RECORD_STATUS_ACTIVE,
    ).first()
    if grant is None:
        raise AccessRequestSubmissionError(("active grant is required",))
    if not _grant_has_effective_membership(grant):
        raise AccessRequestSubmissionError(("active grant is required",))
    return grant


def _validate_renew_request(
    grant_type: AccessRequestGrantType,
    grant_expires_at: datetime | None,
    grant: AccessGrant,
) -> None:
    match grant_type:
        case "timed":
            current_expirations = _current_membership_expirations(grant)
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
    grant: AccessGrant,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    current_group_ids = _current_group_ids(grant)
    target_group_ids = {group.id for group in authorization_groups}
    if not target_group_ids.issubset(current_group_ids):
        raise AccessRequestSubmissionError(("target groups must be subset of current grant",))

    current_direct_grants = _current_direct_grants(grant)
    target_direct_grants = _target_direct_grants(direct_grants)
    if not target_direct_grants.issubset(current_direct_grants):
        raise AccessRequestSubmissionError(
            ("target direct grants must be subset of current grant",),
        )
    if target_group_ids == current_group_ids and target_direct_grants == current_direct_grants:
        raise AccessRequestSubmissionError(("revoke request must reduce current grant",))


def _validate_renew_targets(
    grant: AccessGrant,
    authorization_groups: tuple[AuthorizationGroup, ...],
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> None:
    if {group.id for group in authorization_groups} != _current_group_ids(grant):
        raise AccessRequestSubmissionError(("renew request must keep current groups",))
    if _target_direct_grants(direct_grants) != _current_direct_grants(grant):
        raise AccessRequestSubmissionError(("renew request must keep current direct grants",))


def _current_group_ids(grant: AccessGrant) -> set[int]:
    return set(
        AccessGrantGroup.objects.filter(grant=grant).values_list(
            "authorization_group_id",
            flat=True,
        ),
    )


def _current_direct_grants(grant: AccessGrant) -> set[tuple[int, str]]:
    return set(
        AccessGrantPermission.objects.filter(grant=grant).values_list(
            "permission_id",
            "scope_key",
        ),
    )


def _target_direct_grants(
    direct_grants: tuple[ScopedAccessRequestGrant, ...],
) -> set[tuple[int, str]]:
    return {(grant.permission.id, grant.scope_key) for grant in direct_grants}


def _grant_has_effective_membership(grant: AccessGrant) -> bool:
    now = timezone.now()
    effective = Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    return AccessGrantGroup.objects.filter(effective, grant=grant).exists() or (
        AccessGrantPermission.objects.filter(effective, grant=grant).exists()
    )


def _current_membership_expirations(grant: AccessGrant) -> tuple[datetime | None, ...]:
    group_expirations = AccessGrantGroup.objects.filter(grant=grant).values_list(
        "expires_at",
        flat=True,
    )
    direct_expirations = AccessGrantPermission.objects.filter(grant=grant).values_list(
        "expires_at",
        flat=True,
    )
    return (*group_expirations, *direct_expirations)


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

from __future__ import annotations

import pytest

from easyauth.access_requests.models import (
    AccessRequest,
    AccessRequestGroup,
    AccessRequestPermission,
)
from easyauth.access_requests.services import (
    AccessRequestIdempotencyConflictError,
    AccessRequestService,
    AccessRequestSubmission,
)
from easyauth.access_requests.submission_types import ScopedAccessRequestGrant
from easyauth.accounts.models import UserMirror
from easyauth.applications.models import (
    App,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    Permission,
)
from easyauth.audit.models import AuditLog

pytestmark = pytest.mark.django_db

EXPECTED_CANONICAL_TARGET_COUNT = 2
EXPECTED_CROSS_USER_RECORD_COUNT = 2


def test_same_key_and_payload_returns_original_without_duplicate_writes() -> None:
    user, app, groups, permissions, approvers = _submission_catalog("same-payload")
    submission = _submission(
        user=user,
        app=app,
        groups=(groups[0],),
        permissions=(permissions[0],),
        approvers=(approvers[0],),
        idempotency_key="same-payload-key",
    )

    original = AccessRequestService.submit_access_request(submission)
    replayed = AccessRequestService.submit_access_request(submission)

    assert replayed.id == original.id
    assert replayed.payload_digest == original.payload_digest
    assert AccessRequest.objects.count() == 1
    assert AccessRequestGroup.objects.filter(access_request=original).count() == 1
    assert AccessRequestPermission.objects.filter(access_request=original).count() == 1
    assert AuditLog.objects.filter(event_type="access_request_submitted").count() == 1


def test_reordered_and_duplicate_targets_and_approvers_have_same_digest() -> None:
    user, app, groups, permissions, approvers = _submission_catalog("canonical-payload")
    original = AccessRequestService.submit_access_request(
        _submission(
            user=user,
            app=app,
            groups=groups,
            permissions=permissions,
            approvers=approvers,
            idempotency_key="canonical-payload-key",
        ),
    )

    replayed = AccessRequestService.submit_access_request(
        _submission(
            user=user,
            app=app,
            groups=(groups[1], groups[0], groups[1]),
            permissions=(permissions[1], permissions[0], permissions[1]),
            approvers=(f" {approvers[1]} ", approvers[0], approvers[1]),
            idempotency_key="canonical-payload-key",
        ),
    )

    assert replayed.id == original.id
    assert replayed.payload_digest == original.payload_digest
    assert AccessRequest.objects.count() == 1
    assert (
        AccessRequestGroup.objects.filter(access_request=original).count()
        == EXPECTED_CANONICAL_TARGET_COUNT
    )
    assert (
        AccessRequestPermission.objects.filter(access_request=original).count()
        == EXPECTED_CANONICAL_TARGET_COUNT
    )
    assert AuditLog.objects.filter(event_type="access_request_submitted").count() == 1


def test_same_key_with_different_payload_raises_conflict() -> None:
    user, app, groups, permissions, approvers = _submission_catalog("payload-conflict")
    original = AccessRequestService.submit_access_request(
        _submission(
            user=user,
            app=app,
            groups=(groups[0],),
            permissions=(permissions[0],),
            approvers=(approvers[0],),
            idempotency_key="payload-conflict-key",
            reason="首次申请",
        ),
    )

    with pytest.raises(AccessRequestIdempotencyConflictError):
        _ = AccessRequestService.submit_access_request(
            _submission(
                user=user,
                app=app,
                groups=(groups[0],),
                permissions=(permissions[0],),
                approvers=(approvers[0],),
                idempotency_key="payload-conflict-key",
                reason="修改后的申请",
            ),
        )

    assert AccessRequest.objects.get() == original
    assert AuditLog.objects.filter(event_type="access_request_submitted").count() == 1


def test_different_users_can_reuse_idempotency_key() -> None:
    first_user, app, groups, permissions, approvers = _submission_catalog("cross-user")
    second_user = UserMirror.objects.create(authentik_user_id="cross-user-second-user")

    first = AccessRequestService.submit_access_request(
        _submission(
            user=first_user,
            app=app,
            groups=(groups[0],),
            permissions=(permissions[0],),
            approvers=(approvers[0],),
            idempotency_key="shared-user-key",
        ),
    )
    second = AccessRequestService.submit_access_request(
        _submission(
            user=second_user,
            app=app,
            groups=(groups[0],),
            permissions=(permissions[0],),
            approvers=(approvers[0],),
            idempotency_key="shared-user-key",
        ),
    )

    assert first.id != second.id
    assert (
        AccessRequest.objects.filter(idempotency_key="shared-user-key").count()
        == EXPECTED_CROSS_USER_RECORD_COUNT
    )
    assert (
        AuditLog.objects.filter(event_type="access_request_submitted").count()
        == EXPECTED_CROSS_USER_RECORD_COUNT
    )


def test_replay_precedes_dynamic_submission_validation() -> None:
    user, app, groups, permissions, approvers = _submission_catalog("validation-order")
    submission = _submission(
        user=user,
        app=app,
        groups=(groups[0],),
        permissions=(permissions[0],),
        approvers=(approvers[0],),
        idempotency_key="validation-order-key",
    )
    original = AccessRequestService.submit_access_request(submission)
    app.is_active = False
    app.save(update_fields=["is_active"])

    replayed = AccessRequestService.submit_access_request(submission)

    assert replayed.id == original.id
    assert AccessRequest.objects.count() == 1
    assert AuditLog.objects.filter(event_type="access_request_submitted").count() == 1


def _submission_catalog(
    prefix: str,
) -> tuple[
    UserMirror,
    App,
    tuple[AuthorizationGroup, AuthorizationGroup],
    tuple[Permission, Permission],
    tuple[str, str],
]:
    user = UserMirror.objects.create(authentik_user_id=f"{prefix}-user")
    approvers = (
        UserMirror.objects.create(authentik_user_id=f"{prefix}-approver-a"),
        UserMirror.objects.create(authentik_user_id=f"{prefix}-approver-b"),
    )
    app = App.objects.create(app_key=f"{prefix}-app", name=f"{prefix} app")
    _ = AppScope.objects.create(app=app, key="GLOBAL", name="全局")
    groups = (
        AuthorizationGroup.objects.create(
            app=app,
            key="group-a",
            kind="role",
            name="权限组 A",
        ),
        AuthorizationGroup.objects.create(
            app=app,
            key="group-b",
            kind="role",
            name="权限组 B",
        ),
    )
    for group in groups:
        _ = ApprovalRule.objects.create(
            app=app,
            authorization_group=group,
            approver_userids=[approvers[0].authentik_user_id],
        )
    permissions = (
        Permission.objects.create(
            app=app,
            key="permission.a",
            name="权限 A",
            supported_scopes=["GLOBAL"],
        ),
        Permission.objects.create(
            app=app,
            key="permission.b",
            name="权限 B",
            supported_scopes=["GLOBAL"],
        ),
    )
    return (
        user,
        app,
        groups,
        permissions,
        (approvers[0].authentik_user_id, approvers[1].authentik_user_id),
    )


def _submission(  # noqa: PLR0913
    *,
    user: UserMirror,
    app: App,
    groups: tuple[AuthorizationGroup, ...],
    permissions: tuple[Permission, ...],
    approvers: tuple[str, ...],
    idempotency_key: str,
    reason: str = "申请业务权限",
) -> AccessRequestSubmission:
    return AccessRequestSubmission(
        user=user,
        app=app,
        authorization_groups=groups,
        direct_grants=tuple(
            ScopedAccessRequestGrant(permission=permission, scope_key="GLOBAL")
            for permission in permissions
        ),
        approver_user_ids=approvers,
        grant_type="permanent",
        grant_expires_at=None,
        reason=reason,
        actor_type="user",
        actor_id=user.authentik_user_id,
        idempotency_key=idempotency_key,
    )

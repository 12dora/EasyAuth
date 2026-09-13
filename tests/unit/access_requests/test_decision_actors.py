from __future__ import annotations

import pytest
from django.utils import timezone

from easyauth.access_requests.decision_actors import (
    MISSING_DECISION_ACTOR_EMPTY,
    MISSING_DECISION_ACTOR_RAISE,
    AccessRequestDecisionActorMissingError,
    decided_by_names,
)
from easyauth.access_requests.models import (
    DECISION_ACTOR_CONSOLE_ADMIN,
    DECISION_ACTOR_USER,
    GRANT_TYPE_PERMANENT,
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_SUBMITTED,
    AccessRequest,
)
from easyauth.accounts.models import UserMirror
from easyauth.admin_console.operations_payloads import (
    decided_by_names as console_decided_by_names,
)
from easyauth.applications.models import App

pytestmark = pytest.mark.django_db


def test_raise_policy_resolves_user_actor_and_omits_console_admin() -> None:
    user_actor = UserMirror.objects.create(authentik_user_id="decider-user", name="已决审批人")
    user_decision = _approved_request(
        "raise-user",
        "raise-user-app",
        decided_by=user_actor.authentik_user_id,
        actor_type=DECISION_ACTOR_USER,
    )
    admin_decision = _approved_request(
        "raise-admin",
        "raise-admin-app",
        decided_by="console-admin-actor",
        actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
    )

    names = decided_by_names(
        (user_decision, admin_decision),
        actor_types=frozenset({DECISION_ACTOR_USER}),
        missing=MISSING_DECISION_ACTOR_RAISE,
    )

    assert names == {user_decision.id: "已决审批人"}
    assert names.get(admin_decision.id) is None


def test_raise_policy_fails_when_user_actor_mirror_missing() -> None:
    access_request = _approved_request(
        "raise-missing",
        "raise-missing-app",
        decided_by="missing-decider-id",
        actor_type=DECISION_ACTOR_USER,
    )

    with pytest.raises(AccessRequestDecisionActorMissingError, match="missing-decider-id"):
        decided_by_names(
            (access_request,),
            actor_types=frozenset({DECISION_ACTOR_USER}),
            missing=MISSING_DECISION_ACTOR_RAISE,
        )


def test_empty_policy_uses_blank_for_missing_and_non_user_actors() -> None:
    user_actor = UserMirror.objects.create(authentik_user_id="ops-decider", name="管理员乙")
    user_decision = _approved_request(
        "empty-user",
        "empty-user-app",
        decided_by=user_actor.authentik_user_id,
        actor_type=DECISION_ACTOR_USER,
    )
    admin_decision = _approved_request(
        "empty-admin",
        "empty-admin-app",
        decided_by="console-admin-actor",
        actor_type=DECISION_ACTOR_CONSOLE_ADMIN,
    )
    pending = _submitted_request("empty-pending", "empty-pending-app")

    names = console_decided_by_names((user_decision, admin_decision, pending))

    assert names == {
        user_decision.id: "管理员乙",
        admin_decision.id: "",
        pending.id: "",
    }
    assert decided_by_names((admin_decision,), missing=MISSING_DECISION_ACTOR_EMPTY) == {
        admin_decision.id: "",
    }


def _approved_request(
    user_key: str,
    app_key: str,
    *,
    decided_by: str,
    actor_type: str,
) -> AccessRequest:
    decided_at = timezone.now()
    user = UserMirror.objects.create(authentik_user_id=user_key)
    app = App.objects.create(app_key=app_key, name=app_key)
    return AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_APPROVED,
        grant_type=GRANT_TYPE_PERMANENT,
        reason=user_key,
        idempotency_key=f"{user_key}-key",
        payload_digest="d" * 64,
        approved_at=decided_at,
        decided_at=decided_at,
        decided_by=decided_by,
        decision_actor_type=actor_type,
    )


def _submitted_request(user_key: str, app_key: str) -> AccessRequest:
    user = UserMirror.objects.create(authentik_user_id=user_key)
    app = App.objects.create(app_key=app_key, name=app_key)
    return AccessRequest.objects.create(
        user=user,
        app=app,
        status=REQUEST_STATUS_SUBMITTED,
        grant_type=GRANT_TYPE_PERMANENT,
        reason=user_key,
        idempotency_key=f"{user_key}-key",
        payload_digest="d" * 64,
    )

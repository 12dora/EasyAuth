from __future__ import annotations

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.accounts.person_payload import person_payload
from easyauth.admin_console.operations_payloads import person_ref_or_none

pytestmark = pytest.mark.django_db


def test_person_ref_or_none_returns_payload_when_user_exists() -> None:
    user = UserMirror.objects.create(
        authentik_user_id="ops-person-ref-user",
        name="胡玉琴A",
        department="安环部",
    )
    labels = {user.authentik_user_id: "捷发-安环部"}
    users = {user.authentik_user_id: user}

    assert person_ref_or_none(user.authentik_user_id, users=users, department_labels=labels) == (
        person_payload(user, labels)
    )


def test_person_ref_or_none_is_null_for_unknown_or_system_ids() -> None:
    assert (
        person_ref_or_none("directory_sync", users={}, department_labels={}) is None
    )
    assert person_ref_or_none("missing-user", users={}, department_labels={}) is None

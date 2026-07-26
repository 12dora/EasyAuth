from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from easyauth.accounts.models import UserMirror

pytestmark = pytest.mark.django_db


def test_authentik_user_id_is_globally_unique_when_duplicate_user_is_cleaned() -> None:
    # Given
    _ = UserMirror.objects.create(authentik_user_id="authentik-user-001", name="张三")
    duplicate = UserMirror(authentik_user_id="authentik-user-001", name="张三重复")

    # When / Then
    with pytest.raises(ValidationError):
        duplicate.full_clean()


@pytest.mark.parametrize("status", ["active", "disabled", "departed"])
def test_status_accepts_supported_values_when_user_is_cleaned(status: str) -> None:
    # Given
    user = UserMirror(
        authentik_user_id=f"authentik-user-{status}",
        status=status,
    )

    # When
    user.full_clean()

    # Then
    assert user.status == status


def test_status_rejects_unknown_value_when_user_is_cleaned() -> None:
    # Given
    user = UserMirror(authentik_user_id="authentik-user-unknown", status="unknown")

    # When / Then
    with pytest.raises(ValidationError):
        user.full_clean()


def test_saved_user_mirror_rejects_physical_delete_when_deleted() -> None:
    # Given
    user = UserMirror.objects.create(authentik_user_id="authentik-user-delete")

    # When / Then
    with pytest.raises(ValidationError):
        _ = user.delete()


def test_user_mirror_queryset_rejects_bulk_delete() -> None:
    # Given
    _ = UserMirror.objects.create(authentik_user_id="authentik-user-bulk-delete")

    # When / Then
    with pytest.raises(ValidationError):
        _ = UserMirror.objects.filter(authentik_user_id="authentik-user-bulk-delete").delete()


def test_dingtalk_identity_binding_is_unique_in_database() -> None:
    # Given
    _ = UserMirror.objects.create(
        authentik_user_id="authentik-dt-unique-a",
        dingtalk_source_slug="source-unique",
        dingtalk_corp_id="corp-unique",
        dingtalk_userid="dt-unique",
    )

    # When / Then
    with pytest.raises(IntegrityError):
        _ = UserMirror.objects.create(
            authentik_user_id="authentik-dt-unique-b",
            dingtalk_source_slug="source-unique",
            dingtalk_corp_id="corp-unique",
            dingtalk_userid="dt-unique",
        )


def test_dingtalk_identity_binding_is_scoped_by_source() -> None:
    # Given
    _ = UserMirror.objects.create(
        authentik_user_id="authentik-dt-source-a",
        dingtalk_source_slug="source-a",
        dingtalk_corp_id="corp-source",
        dingtalk_userid="dt-source",
    )

    # When / Then
    _ = UserMirror.objects.create(
        authentik_user_id="authentik-dt-source-b",
        dingtalk_source_slug="source-b",
        dingtalk_corp_id="corp-source",
        dingtalk_userid="dt-source",
    )

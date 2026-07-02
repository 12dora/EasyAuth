from __future__ import annotations

from easyauth.api.serializers import (
    PermissionQueryObject,
    PermissionQueryResponseInput,
    PermissionQueryResponseSerializer,
)

EXPECTED_VERSION = 7
EXPECTED_CATALOG_VERSION = 3


def test_permission_query_response_serializer_keeps_regular_grant_without_resolved() -> None:
    # Given
    payload = _permission_query_payload(
        grants=[
            {
                "permission": "account.read",
                "scope": "SELF",
                "source_type": "direct",
                "source_key": "",
            },
        ],
    )

    # When
    serializer = PermissionQueryResponseSerializer(data=payload)

    # Then
    assert serializer.is_valid(), serializer.errors
    assert serializer.data["grants"] == [
        {
            "permission": "account.read",
            "scope": "SELF",
            "source_type": "direct",
            "source_key": "",
        },
    ]


def test_permission_query_response_serializer_keeps_managed_users_resolved_payload() -> None:
    # Given
    payload = _permission_query_payload(
        grants=[
            {
                "permission": "account.read",
                "scope": "MANAGED_USERS",
                "source_type": "direct",
                "source_key": "",
                "resolved": {
                    "user_ids": ["user-001", "user-002"],
                    "resolver": "managed-users-v1",
                    "resolved_at": "2026-06-05T10:20:30Z",
                },
            },
        ],
    )

    # When
    serializer = PermissionQueryResponseSerializer(data=payload)

    # Then
    assert serializer.is_valid(), serializer.errors
    grant = serializer.data["grants"][0]
    assert "resolved" in grant
    assert grant["resolved"] == {
        "user_ids": ["user-001", "user-002"],
        "resolver": "managed-users-v1",
        "resolved_at": "2026-06-05T10:20:30Z",
    }


def test_permission_query_response_serializer_rejects_invalid_managed_users_resolved() -> None:
    # Given
    payload = _permission_query_payload(
        grants=[
            {
                "permission": "account.read",
                "scope": "MANAGED_USERS",
                "source_type": "direct",
                "source_key": "",
                "resolved": {
                    "user_ids": ["user-001", 2],
                    "resolver": "managed-users-v1",
                    "resolved_at": "2026-06-05T10:20:30Z",
                },
            },
        ],
    )

    # When
    serializer = PermissionQueryResponseSerializer(data=payload)

    # Then
    assert serializer.is_valid() is False
    assert serializer.errors == {"grants": ["invalid"]}


def test_permission_query_response_serializer_rejects_resolved_on_regular_grant() -> None:
    # Given
    payload = _permission_query_payload(
        grants=[
            {
                "permission": "account.read",
                "scope": "SELF",
                "source_type": "direct",
                "source_key": "",
                "resolved": {
                    "user_ids": ["user-001"],
                    "resolver": "managed-users-v1",
                    "resolved_at": "2026-06-05T10:20:30Z",
                },
            },
        ],
    )

    # When
    serializer = PermissionQueryResponseSerializer(data=payload)

    # Then
    assert serializer.is_valid() is False
    assert serializer.errors == {"grants": ["invalid"]}


def _permission_query_payload(
    *,
    grants: list[PermissionQueryObject],
) -> PermissionQueryResponseInput:
    return {
        "user_id": "user-001",
        "app_key": "crm",
        "groups": [],
        "grants": grants,
        "grant_version": EXPECTED_VERSION,
        "catalog_version": EXPECTED_CATALOG_VERSION,
        "snapshot_version": "7.3",
        "expires_at": "2026-06-05T10:20:30Z",
    }

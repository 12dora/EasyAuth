from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from easyauth.integrations.authentik.payloads import (
    AuthentikPayloadError,
    parse_authentik_payload,
)

if TYPE_CHECKING:
    from easyauth.integrations.authentik.payloads import AuthentikPayloadInput


def test_s10_parse_user_uid_maps_to_authentik_user_id_and_active_status() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "user": {
            "uid": "s10-payload-user-uid",
            "name": "张三",
            "email": "zhangsan@example.test",
            "attributes": {"department": "研发部"},
        },
        "is_active": True,
    }

    # When
    profile = parse_authentik_payload(payload)

    # Then
    assert profile.authentik_user_id == "s10-payload-user-uid"
    assert profile.status == "active"
    assert profile.name == "张三"
    assert profile.email == "zhangsan@example.test"
    assert profile.department == "研发部"


def test_s10_parse_payload_maps_dingtalk_summary_fields() -> None:
    payload: AuthentikPayloadInput = {
        "user": {
            "uid": "s10-payload-dingtalk",
            "attributes": {
                "department": "旧部门",
                "dingtalk": {
                    "corp_id": "corp-1",
                    "user_id": "user-1",
                    "union_id": "union-1",
                    "job_number": "E001",
                    "name": "钉钉张三",
                    "mobile": "13800000000",
                    "raw": {"ignored": True},
                },
                "dingtalk_org": {
                    "departments": [{"name": "销售部"}],
                    "manager": {"user_id": "manager-1", "name": "主管"},
                    "email": "manager@example.test",
                },
            },
        },
        "is_active": True,
    }

    profile = parse_authentik_payload(payload)

    assert profile.name == "钉钉张三"
    assert profile.dingtalk_corp_id == "corp-1"
    assert profile.dingtalk_userid == "user-1"
    assert profile.dingtalk_union_id == "union-1"
    assert profile.employee_number == "E001"
    assert profile.department == "销售部"
    assert profile.manager_userid == "manager-1"


def test_s10_parse_context_sub_maps_oidc_subject_to_authentik_user_id() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "context": {"sub": "s10-payload-context-sub"},
        "is_active": True,
    }

    # When
    profile = parse_authentik_payload(payload)

    # Then
    assert profile.authentik_user_id == "s10-payload-context-sub"
    assert profile.status == "active"


def test_s10_parse_context_attribute_uid_maps_to_authentik_user_id() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "context": {"attributes": {"uid": "s10-payload-attribute-uid"}},
        "is_active": True,
    }

    # When
    profile = parse_authentik_payload(payload)

    # Then
    assert profile.authentik_user_id == "s10-payload-attribute-uid"


def test_s10_parse_false_is_active_maps_to_disabled_status() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "user": {"uid": "s10-payload-disabled"},
        "is_active": False,
    }

    # When
    profile = parse_authentik_payload(payload)

    # Then
    assert profile.status == "disabled"


def test_s10_parse_inactive_status_maps_to_disabled_status() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "user": {"uid": "s10-payload-inactive"},
        "status": "inactive",
    }

    # When
    profile = parse_authentik_payload(payload)

    # Then
    assert profile.status == "disabled"


def test_s10_parse_departed_attribute_overrides_active_flag() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "user": {
            "uid": "s10-payload-departed",
            "attributes": {"status": "departed"},
        },
        "is_active": True,
    }

    # When
    profile = parse_authentik_payload(payload)

    # Then
    assert profile.status == "departed"


def test_s10_parse_payload_rejects_empty_payload_without_subject() -> None:
    # Given
    payload: AuthentikPayloadInput = {}

    # When / Then
    with pytest.raises(AuthentikPayloadError, match="subject"):
        _ = parse_authentik_payload(payload)


def test_s10_parse_payload_rejects_non_bool_is_active() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "user": {"uid": "s10-payload-bad-active"},
        "is_active": "false",
    }

    # When / Then
    with pytest.raises(AuthentikPayloadError, match="is_active"):
        _ = parse_authentik_payload(payload)


def test_s10_parse_payload_rejects_unsupported_status() -> None:
    # Given
    payload: AuthentikPayloadInput = {
        "user": {"uid": "s10-payload-bad-status"},
        "status": "suspended",
    }

    # When / Then
    with pytest.raises(AuthentikPayloadError, match="status"):
        _ = parse_authentik_payload(payload)


@pytest.mark.parametrize(
    ("payload", "error_field"),
    [
        ({"user": "not-object"}, "user"),
        ({"context": "not-object"}, "context"),
        ({"user": {"uid": ""}}, "user.uid"),
        ({"user": {"uid": "s10-bad-name", "name": 123}}, "user.name"),
        ({"user": {"uid": "s10-bad-attributes", "attributes": "not-object"}}, "attributes"),
        (
            {
                "user": {"uid": "s10-conflict-user"},
                "context": {"sub": "s10-conflict-sub"},
            },
            "subject",
        ),
    ],
)
def test_s10_parse_payload_rejects_malformed_subject_and_profile_fields(
    payload: AuthentikPayloadInput,
    error_field: str,
) -> None:
    # When / Then
    with pytest.raises(AuthentikPayloadError, match=error_field):
        _ = parse_authentik_payload(payload)

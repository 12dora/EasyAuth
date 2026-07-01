from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from easyauth.accounts.models import (
    USER_STATUS_ACTIVE,
    USER_STATUS_DEPARTED,
    USER_STATUS_DISABLED,
)
from easyauth.accounts.status import is_non_active_status, parse_user_status


@pytest.mark.parametrize(
    ("raw_status", "parsed_status"),
    [
        (USER_STATUS_ACTIVE, USER_STATUS_ACTIVE),
        (USER_STATUS_DISABLED, USER_STATUS_DISABLED),
        (USER_STATUS_DEPARTED, USER_STATUS_DEPARTED),
    ],
)
def test_parse_user_status_accepts_supported_values(
    raw_status: str,
    parsed_status: str,
) -> None:
    assert parse_user_status(raw_status) == parsed_status


@pytest.mark.parametrize(
    ("status", "is_non_active"),
    [
        (USER_STATUS_ACTIVE, False),
        (USER_STATUS_DISABLED, True),
        (USER_STATUS_DEPARTED, True),
    ],
)
def test_is_non_active_status_matches_supported_values(
    status: str,
    is_non_active: object,
) -> None:
    assert is_non_active_status(status) is is_non_active


def test_parse_user_status_rejects_unknown_value_with_validation_error() -> None:
    with pytest.raises(ValidationError) as error:
        _ = parse_user_status("unknown")

    assert error.value.message_dict == {"status": ["Unsupported user status: unknown"]}


def test_is_non_active_status_rejects_unknown_value_with_validation_error() -> None:
    with pytest.raises(ValidationError) as error:
        _ = is_non_active_status("unknown")

    assert error.value.message_dict == {"status": ["Unsupported user status: unknown"]}

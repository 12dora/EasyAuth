from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from easyauth.grants.models import (
    GRANT_STATUS_ACTIVE,
    GRANT_STATUS_EXPIRED,
    GRANT_STATUS_REVOKED,
)
from easyauth.grants.status import parse_grant_status


@pytest.mark.parametrize(
    ("raw_status", "parsed_status"),
    [
        (GRANT_STATUS_ACTIVE, GRANT_STATUS_ACTIVE),
        (GRANT_STATUS_REVOKED, GRANT_STATUS_REVOKED),
        (GRANT_STATUS_EXPIRED, GRANT_STATUS_EXPIRED),
    ],
)
def test_parse_grant_status_accepts_supported_values(
    raw_status: str,
    parsed_status: str,
) -> None:
    assert parse_grant_status(raw_status) == parsed_status


def test_parse_grant_status_rejects_unknown_value_with_validation_error() -> None:
    with pytest.raises(ValidationError) as error:
        _ = parse_grant_status("unknown")

    assert error.value.message_dict == {"status": ["Unsupported grant status: unknown"]}

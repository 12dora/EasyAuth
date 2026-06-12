from __future__ import annotations

from typing import Literal, cast

from django.core.exceptions import ValidationError

from easyauth.accounts.models import (
    USER_STATUS_CHOICES,
    USER_STATUS_DEPARTED,
    USER_STATUS_DISABLED,
)

USER_STATUS_VALUES: tuple[str, ...] = tuple(status for status, _label in USER_STATUS_CHOICES)
type UserStatus = Literal["active", "disabled", "departed"]


def parse_user_status(status: str) -> UserStatus:
    if status in USER_STATUS_VALUES:
        return cast("UserStatus", status)
    raise ValidationError({"status": f"Unsupported user status: {status}"})


def is_non_active_status(status: str) -> bool:
    parsed_status = parse_user_status(status)
    return parsed_status in {USER_STATUS_DISABLED, USER_STATUS_DEPARTED}

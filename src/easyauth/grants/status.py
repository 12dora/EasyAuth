from __future__ import annotations

from typing import Literal, cast

from django.core.exceptions import ValidationError

from easyauth.grants.models import GRANT_STATUS_VALUES

type GrantStatus = Literal["active", "revoked", "expired"]


def parse_grant_status(status: str) -> GrantStatus:
    if status in GRANT_STATUS_VALUES:
        return cast("GrantStatus", status)
    raise ValidationError({"status": f"Unsupported grant status: {status}"})

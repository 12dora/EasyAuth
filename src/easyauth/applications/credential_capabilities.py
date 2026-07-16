from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from django.core.exceptions import ValidationError

if TYPE_CHECKING:
    from collections.abc import Sequence

CAPABILITY_DIRECTORY: Final = "directory"
CAPABILITY_NOTIFY: Final = "notify"
CAPABILITY_VALUES: Final[frozenset[str]] = frozenset(
    (CAPABILITY_DIRECTORY, CAPABILITY_NOTIFY),
)
CAPABILITIES_TYPE_MESSAGE: Final = "凭据 capabilities 必须是字符串数组。"
CAPABILITIES_VALUE_MESSAGE: Final = "凭据 capabilities 只能包含 directory、notify。"
CAPABILITIES_DUPLICATE_MESSAGE: Final = "凭据 capabilities 不得重复。"


def validate_credential_capabilities(value: object) -> None:
    if not isinstance(value, list):
        raise ValidationError(CAPABILITIES_TYPE_MESSAGE)
    raw_items = cast("list[object]", value)
    if any(not isinstance(item, str) or item not in CAPABILITY_VALUES for item in raw_items):
        raise ValidationError(CAPABILITIES_VALUE_MESSAGE)
    items = cast("list[str]", raw_items)
    if len(items) != len(set(items)):
        raise ValidationError(CAPABILITIES_DUPLICATE_MESSAGE)


def normalize_credential_capabilities(capabilities: Sequence[str]) -> list[str]:
    items = list(capabilities)
    validate_credential_capabilities(items)
    return sorted(items)

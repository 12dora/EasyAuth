from __future__ import annotations

from types import MappingProxyType
from typing import cast

import pytest

from easyauth.usage.registry import (
    CATEGORIES,
    UnknownUsageCategoryError,
    UsageCategory,
    category,
)


def test_categories_is_closed_mapping() -> None:
    assert isinstance(CATEGORIES, MappingProxyType)
    with pytest.raises(TypeError):
        cast("dict[str, UsageCategory]", CATEGORIES)["token"] = CATEGORIES["token"]


def test_lookup_unknown_key_fails_fast() -> None:
    with pytest.raises(UnknownUsageCategoryError, match="未知的用量类别") as exc_info:
        _ = category("not-a-category")
    assert isinstance(exc_info.value, KeyError)
    assert exc_info.value.category_key == "not-a-category"


def test_known_category_fields() -> None:
    token = category("token")
    assert token.metric == "api"
    assert token.billed is False
    assert token.priority == "p0"
    notify = category("notify_send")
    assert notify.billed is True
    assert notify.priority == "p1"
    internal = category("internal_netbird")
    assert internal.metric == "internal"
    assert internal.priority is None
    assert internal.billed is False

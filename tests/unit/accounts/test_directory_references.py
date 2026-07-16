from __future__ import annotations

import pytest

from easyauth.accounts.directory_references import (
    InvalidDirectoryReferenceError,
    build_dingtalk_user_ref,
    parse_user_ref,
)


def test_scoped_user_ref_round_trips_reserved_and_unicode_components() -> None:
    reference = build_dingtalk_user_ref(
        source_slug="ding:talk/主",
        corp_id="corp:甲/乙",
        user_id="user:一/二",
    )

    parsed = parse_user_ref(reference)

    assert parsed.scoped is True
    assert parsed.source_slug == "ding:talk/主"
    assert parsed.corp_id == "corp:甲/乙"
    assert parsed.identifier == "user:一/二"
    assert "/" not in reference


@pytest.mark.parametrize(
    "reference",
    [
        "dt:v1:only-two-parts",
        "dt:v1:***:Y29ycA:dXNlcg",
        "dt:v1::Y29ycA:dXNlcg",
    ],
)
def test_scoped_user_ref_rejects_malformed_encoding(reference: str) -> None:
    with pytest.raises(InvalidDirectoryReferenceError):
        _ = parse_user_ref(reference)

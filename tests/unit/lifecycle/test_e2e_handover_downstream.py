from __future__ import annotations

from http import HTTPStatus
from typing import Any

import pytest

from scripts.e2e_handover_downstream import (
    HandoverBusinessError,
    WebhookEvent,
    on_execute,
)


def _event(assignments: object) -> WebhookEvent:
    return WebhookEvent(
        event_type="lifecycle.handover.execute",
        delivery_id="e2e-delivery",
        timestamp=1,
        payload={"assignments": assignments},
    )


def _expected_assignment() -> list[dict[str, Any]]:
    return [
        {
            "asset_type": "document",
            "default_action": "transfer",
            "default_to_user_id": "e2e-peer",
            "overrides": [
                {"id": "doc-1", "action": "skip", "to_user_id": None},
                {"id": "doc-2", "action": "skip", "to_user_id": None},
            ],
        },
    ]


def test_execute_requires_document_transfer_with_exact_two_skip_overrides() -> None:
    assert on_execute(_event(_expected_assignment())) == {
        "summary": {
            "document": {
                "transferred": 1,
                "released": 0,
                "skipped": 2,
                "merged": 0,
                "failed": 0,
            },
        },
    }


@pytest.mark.parametrize(
    "assignments",
    [
        None,
        [],
        ["bad-row"],
        [{**_expected_assignment()[0], "asset_type": "unknown"}],
        [{**_expected_assignment()[0], "default_to_user_id": None}],
        [{**_expected_assignment()[0], "overrides": []}],
        [
            {
                **_expected_assignment()[0],
                "overrides": [
                    {"id": "doc-1", "action": "skip", "to_user_id": None},
                    {"id": "doc-3", "action": "skip", "to_user_id": None},
                ],
            },
        ],
    ],
)
def test_execute_rejects_incomplete_or_malformed_assignments(assignments: object) -> None:
    with pytest.raises(HandoverBusinessError) as exc_info:
        on_execute(_event(assignments))

    assert exc_info.value.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert exc_info.value.code == "e2e_execute_payload_invalid"

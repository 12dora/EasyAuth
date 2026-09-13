from __future__ import annotations

import pytest

from easyauth.portal.status_text import status_label, status_tone


@pytest.mark.parametrize(
    ("status", "expected_label", "expected_tone"),
    [
        ("submitted", "等待审批", "primary"),
        ("approved", "已通过", "secondary"),
        ("grant_applied", "已生效", "success"),
        ("rejected", "已拒绝", "danger"),
        ("grant_failed", "落库失败", "danger"),
        ("grant_conflict", "已冲突", "danger"),
        ("grant_expired", "已过期", "danger"),
        ("withdrawn", "已撤回", "secondary"),
        ("unexpected", "未知", "secondary"),
    ],
)
def test_status_text_uses_single_portal_copy_source(
    status: str,
    expected_label: str,
    expected_tone: str,
) -> None:
    assert status_label(status) == expected_label
    assert status_tone(status) == expected_tone

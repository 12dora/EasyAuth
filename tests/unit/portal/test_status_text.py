from __future__ import annotations

import pytest

from easyauth.portal.status_text import status_label, status_tone


@pytest.mark.parametrize(
    ("status", "expected_label", "expected_tone"),
    [
        ("submitted", "等待审批", "primary"),
        ("approved", "审批已通过, 等待授权落库", "secondary"),
        ("grant_applied", "授权已落库, 权限已生效", "success"),
        ("rejected", "已拒绝", "danger"),
        ("grant_failed", "授权落库失败", "danger"),
        ("grant_expired", "授权期限已过, 未应用", "danger"),
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

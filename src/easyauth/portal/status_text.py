from __future__ import annotations

from typing import Final, Literal

from easyauth.access_requests.models import (
    REQUEST_STATUS_APPROVED,
    REQUEST_STATUS_GRANT_APPLIED,
    REQUEST_STATUS_GRANT_EXPIRED,
    REQUEST_STATUS_GRANT_FAILED,
    REQUEST_STATUS_REJECTED,
    REQUEST_STATUS_SUBMITTED,
)

type StatusTone = Literal["primary", "secondary", "success", "danger"]

_STATUS_LABELS: Final[dict[str, str]] = {
    REQUEST_STATUS_SUBMITTED: "等待审批",
    REQUEST_STATUS_APPROVED: "审批已通过, 等待授权落库",
    REQUEST_STATUS_GRANT_APPLIED: "授权已落库, 权限已生效",
    REQUEST_STATUS_REJECTED: "已拒绝",
    REQUEST_STATUS_GRANT_FAILED: "授权落库失败",
    REQUEST_STATUS_GRANT_EXPIRED: "授权期限已过, 未应用",
}

_STATUS_TONES: Final[dict[str, StatusTone]] = {
    REQUEST_STATUS_SUBMITTED: "primary",
    REQUEST_STATUS_APPROVED: "secondary",
    REQUEST_STATUS_GRANT_APPLIED: "success",
    REQUEST_STATUS_REJECTED: "danger",
    REQUEST_STATUS_GRANT_FAILED: "danger",
    REQUEST_STATUS_GRANT_EXPIRED: "danger",
}


def status_label(status: str) -> str:
    return _STATUS_LABELS.get(status, "未知")


def status_tone(status: str) -> StatusTone:
    return _STATUS_TONES.get(status, "secondary")

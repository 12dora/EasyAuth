"""交接错误的统一脱敏与 UTF-8 字节限长投影（冻结契约 00 §10.6）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from easyauth.applications.ops_models import JsonValue

PUBLIC_ERROR_MAX_BYTES: Final = 200
RAW_ERROR_MAX_BYTES: Final = 2000

_BEARER_RE = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIAL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@]+(?::[^\s/@]*)?@")
_SENSITIVE_FIELD_RE = re.compile(
    r"(?i)([\"']?(?:authorization|token|access_token|refresh_token|api[_-]?key|secret|password|passwd|sub|dtuid)[\"']?\s*[:=]\s*)([\"']?)([^\"'\s,;}]+)",
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_OPAQUE_SECRET_RE = re.compile(r"\b(?:sk|ak|eat)-[A-Za-z0-9_-]{8,}|\bwhsec_[A-Za-z0-9_-]{8,}")
_WHITELIST_KEYS: Final = frozenset({"code", "message", "traceId"})


@dataclass(frozen=True, slots=True)
class ErrorProjection:
    public: str
    raw: str


def truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def redact_handover_error(value: str) -> str:
    redacted = _URL_CREDENTIAL_RE.sub(r"\1[已隐藏]@", value)
    redacted = _BEARER_RE.sub(r"\1[已隐藏]", redacted)
    redacted = _SENSITIVE_FIELD_RE.sub(r"\1\2[已隐藏]", redacted)
    redacted = _EMAIL_RE.sub("[人员标识已隐藏]", redacted)
    return _OPAQUE_SECRET_RE.sub("[密钥已隐藏]", redacted)


def project_handover_error(
    *,
    error: object,
    status_code: int | None = None,
    payload: dict[str, JsonValue] | None = None,
    raw_body: str = "",
    stable_message: str | None = None,
) -> ErrorProjection:
    base = stable_message or _stable_status_message(status_code) or str(error)
    if status_code is not None:
        base = f"HTTP {status_code} {base}"
    details = _whitelisted_details(payload)
    public_source = base if not details else f"{base}；{details}"
    raw_source = raw_body
    if not raw_source and payload is not None:
        raw_source = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if not raw_source:
        raw_source = str(error)
    return ErrorProjection(
        public=truncate_utf8(redact_handover_error(public_source), PUBLIC_ERROR_MAX_BYTES),
        raw=truncate_utf8(redact_handover_error(raw_source), RAW_ERROR_MAX_BYTES),
    )


def _whitelisted_details(payload: dict[str, JsonValue] | None) -> str:
    if not payload:
        return ""
    found: dict[str, str] = {}

    def visit(value: JsonValue) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _WHITELIST_KEYS and key not in found and isinstance(
                    child,
                    str | int | float | bool,
                ):
                    found[key] = truncate_utf8(str(child), PUBLIC_ERROR_MAX_BYTES)
                elif isinstance(child, dict | list):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    keys = ("code", "message", "traceId")
    return "；".join(f"{key}={found[key]}" for key in keys if key in found)


def _stable_status_message(status_code: int | None) -> str:
    if status_code == HTTPStatus.BAD_REQUEST:
        return "请求被应用拒绝"
    if status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        return "签名校验失败，请检查该应用的 webhook 密钥"
    if status_code == HTTPStatus.CONFLICT:
        return "应用拒绝了本次交接"
    if status_code == HTTPStatus.PRECONDITION_FAILED:
        return "清单已变化，请重新预演"
    if status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE:
        return "请求体过大，请分批执行"
    if status_code == HTTPStatus.UNPROCESSABLE_ENTITY:
        return "应用声明与实现不一致"
    if status_code == HTTPStatus.LOCKED:
        return "该应用中部分对象正在审批或锁定，解除后请重新预演"
    if status_code == HTTPStatus.TOO_MANY_REQUESTS:
        return "应用侧限流，请稍后重试"
    if status_code is not None and status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        return "应用内部错误"
    return ""

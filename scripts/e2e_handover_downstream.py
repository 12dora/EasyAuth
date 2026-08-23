#!/usr/bin/env python3
"""全栈 E2E 下游交接 stub: 基于 vendored easyauth-app-sdk 内核, 无 FastAPI 依赖。

EasyAuth 经签名 webhook 调用本进程的 ``/api/v1/easyauth/lifecycle/handover``。
返回确定性 preview / items / execute 载荷, 供门户自助交接 e2e 走真实链路。

启动::

    PYTHONPATH=sdk/python/src \\
      EASYAUTH_E2E_DOWNSTREAM_SECRET=whsec_e2e_handover \\
      EASYAUTH_E2E_DOWNSTREAM_PORT=18010 \\
      .venv/bin/python scripts/e2e_handover_downstream.py

仅用于本地/CI 全栈 E2E, 不得部署到生产。
"""

from __future__ import annotations

import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SDK_SRC = REPO_ROOT / "sdk" / "python" / "src"
if str(SDK_SRC) not in sys.path:
    sys.path.insert(0, str(SDK_SRC))

from easyauth_app_sdk.lifecycle import (  # noqa: E402
    DEFAULT_HANDOVER_PATH,
    HandoverBusinessError,
    lifecycle_http_response,
)
from easyauth_app_sdk.webhook import WebhookEvent  # noqa: E402

ASSET_TYPE = "document"
ASSET_LABEL = "文档"
ITEMS: list[dict[str, str]] = [
    {"id": "doc-1", "label": "文档甲", "hint": "E2E item 1"},
    {"id": "doc-2", "label": "文档乙", "hint": "E2E item 2"},
    {"id": "doc-3", "label": "文档丙", "hint": "E2E item 3"},
]
HEALTH_PATH = "/health"
EXECUTE_PAYLOAD_INVALID_CODE = "e2e_execute_payload_invalid"
EXECUTE_PAYLOAD_INVALID_MESSAGE = "全栈 E2E execute 载荷与预期分配不一致。"
EXPECTED_OVERRIDE_IDS = frozenset({"doc-1", "doc-2"})


def _secret() -> str:
    value = os.environ.get("EASYAUTH_E2E_DOWNSTREAM_SECRET", "").strip()
    if not value:
        message = "EASYAUTH_E2E_DOWNSTREAM_SECRET 未设置。"
        raise RuntimeError(message)
    return value


def _expected_receiver() -> str:
    return os.environ.get("EASYAUTH_E2E_PEER_USER", "e2e-peer").strip() or "e2e-peer"


def _reject_execute_payload() -> None:
    raise HandoverBusinessError(
        422,
        EXECUTE_PAYLOAD_INVALID_CODE,
        EXECUTE_PAYLOAD_INVALID_MESSAGE,
    )


def on_preview(_event: WebhookEvent) -> dict[str, Any]:
    return {
        "snapshot_token": "e2e-snapshot-token",
        "assets": [
            {
                "type": ASSET_TYPE,
                "label": ASSET_LABEL,
                "count": len(ITEMS),
                "detail_supported": True,
                "releasable": False,
            },
        ],
    }


def on_items(event: WebhookEvent) -> dict[str, Any]:
    page = int(event.payload.get("page", 1) or 1)
    page_size = int(event.payload.get("page_size", 50) or 50)
    q = str(event.payload.get("q", "") or "").strip()
    filtered = [
        item
        for item in ITEMS
        if not q or q.lower() in item["label"].lower() or q.lower() in item["id"].lower()
    ]
    start = max(0, (page - 1) * page_size)
    end = start + page_size
    return {
        "items": filtered[start:end],
        "page": page,
        "page_size": page_size,
        "total": len(filtered),
        "unfiltered_total": len(ITEMS),
    }


def on_execute(event: WebhookEvent) -> dict[str, Any]:
    """按 assignments 守恒汇总: transferred+released+skipped+merged+failed == preview count。"""
    assignments = event.payload.get("assignments")
    if not isinstance(assignments, list) or len(assignments) != 1:
        _reject_execute_payload()
    row = assignments[0]
    if not isinstance(row, dict):
        _reject_execute_payload()
    if (
        row.get("asset_type") != ASSET_TYPE
        or row.get("default_action") != "transfer"
        or row.get("default_to_user_id") != _expected_receiver()
    ):
        _reject_execute_payload()
    overrides = row.get("overrides")
    if not isinstance(overrides, list) or len(overrides) != len(EXPECTED_OVERRIDE_IDS):
        _reject_execute_payload()
    override_ids: set[str] = set()
    for override in overrides:
        if (
            not isinstance(override, dict)
            or override.get("action") != "skip"
            or override.get("to_user_id") is not None
            or not isinstance(override.get("id"), str)
        ):
            _reject_execute_payload()
        override_ids.add(override["id"])
    if override_ids != EXPECTED_OVERRIDE_IDS:
        _reject_execute_payload()
    return {
        "summary": {
            ASSET_TYPE: {
                "transferred": 1,
                "released": 0,
                "skipped": 2,
                "merged": 0,
                "failed": 0,
            },
        },
    }


class HandoverStubHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"[e2e-downstream] {self.address_string()} {format % args}\n")

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == HEALTH_PATH:
            body = b'{"ok":true}\n'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404, "Not Found")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != DEFAULT_HANDOVER_PATH:
            self.send_error(404, "Not Found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Bad Content-Length")
            return
        raw_body = self.rfile.read(length) if length > 0 else b""
        status, headers, body = lifecycle_http_response(
            secret_provider=_secret,
            headers={key: value for key, value in self.headers.items()},
            raw_body=raw_body,
            on_handover_preview=on_preview,
            on_handover_execute=on_execute,
            on_handover_items=on_items,
        )
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.environ.get("EASYAUTH_E2E_DOWNSTREAM_PORT", "18010"))
    # 启动前校验 secret, 避免 EasyAuth 投递时才因空 secret 失败。
    _ = _secret()
    server = ThreadingHTTPServer(("127.0.0.1", port), HandoverStubHandler)
    sys.stderr.write(
        f"[e2e-downstream] listening on http://127.0.0.1:{port}{DEFAULT_HANDOVER_PATH}\n",
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

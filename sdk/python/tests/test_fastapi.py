from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="fastapi 是可选集成 extra, 未安装时跳过。")
pytest.importorskip("starlette", reason="TestClient 依赖 starlette。")

from easyauth_app_sdk.descriptor import DESCRIPTOR_WELL_KNOWN_PATH
from easyauth_app_sdk.fastapi import create_descriptor_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _manifest() -> dict:
    return {
        "schema_version": 1,
        "app": {
            "app_key": "demoapp",
            "name": "Demo App",
            "description": "演示应用",
            "is_active": True,
        },
        "scopes": [{"key": "SELF", "name": "本人"}],
        "permission_groups": [{"key": "demo.item", "name": "演示对象"}],
        "permissions": [
            {
                "key": "demo.item.view",
                "name": "查看演示对象",
                "group_key": "demo.item",
                "supported_scopes": ["SELF"],
            },
        ],
        "authorization_groups": [],
        "approval_rules": [],
    }


def _app(**kwargs: object) -> TestClient:
    api = FastAPI()
    api.include_router(create_descriptor_router(_manifest, **kwargs))
    return TestClient(api)


def test_router_serves_descriptor_json() -> None:
    response = _app().get(DESCRIPTOR_WELL_KNOWN_PATH)

    assert response.status_code == 200
    assert response.json()["manifest"]["app"]["app_key"] == "demoapp"


def test_router_enforces_static_token() -> None:
    client = _app(token="shared-secret")

    assert client.get(DESCRIPTOR_WELL_KNOWN_PATH).status_code == 401
    ok = client.get(
        DESCRIPTOR_WELL_KNOWN_PATH,
        headers={"Authorization": "Bearer shared-secret"},
    )
    assert ok.status_code == 200


def test_router_supports_dynamic_token_validator() -> None:
    client = _app(token_validator=lambda token: token == "db-managed-key")  # noqa: S105

    assert client.get(
        DESCRIPTOR_WELL_KNOWN_PATH,
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 401
    assert client.get(
        DESCRIPTOR_WELL_KNOWN_PATH,
        headers={"Authorization": "Bearer db-managed-key"},
    ).status_code == 200

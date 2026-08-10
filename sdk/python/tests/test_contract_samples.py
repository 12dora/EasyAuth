"""包内 handover v2 契约样本必须存在且可通过 importlib.resources 读取。

样本缺失必须让测试失败, 不允许 skip 通过。
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

_REQUIRED_SAMPLES = (
    "preview_request.json",
    "preview_response.json",
    "items_request.json",
    "items_response.json",
    "execute_request.json",
    "execute_response.json",
)


def _package():
    return resources.files("easyauth_app_sdk.contract_samples.handover_v2")


@pytest.mark.parametrize("name", _REQUIRED_SAMPLES)
def test_contract_sample_is_packaged_and_loadable(name: str) -> None:
    path = _package().joinpath(name)
    assert path.is_file(), f"契约样本缺失: {name}(importlib.resources 读不到即发布失败)"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload, f"契约样本为空: {name}"


def test_request_samples_include_event_type() -> None:
    for name, expected in (
        ("preview_request.json", "lifecycle.handover.preview"),
        ("items_request.json", "lifecycle.handover.items"),
        ("execute_request.json", "lifecycle.handover.execute"),
    ):
        payload = json.loads(_package().joinpath(name).read_text(encoding="utf-8"))
        assert payload["event_type"] == expected


def test_preview_response_has_snapshot_token_and_eight_assets() -> None:
    payload = json.loads(_package().joinpath("preview_response.json").read_text(encoding="utf-8"))
    assert isinstance(payload["snapshot_token"], str) and payload["snapshot_token"]
    assert len(payload["assets"]) == 8
    types = [asset["type"] for asset in payload["assets"]]
    assert types[0] == "customer"
    assert "sample_request_open" in types


def test_execute_summary_has_frozen_five_keys() -> None:
    payload = json.loads(_package().joinpath("execute_response.json").read_text(encoding="utf-8"))
    frozen = {"transferred", "released", "skipped", "merged", "failed"}
    for counts in payload["summary"].values():
        assert set(counts) == frozen

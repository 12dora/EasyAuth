from __future__ import annotations

from typing import cast

from easyauth.applications.models import AppCapability, JsonValue

__all__ = (
    "app_capability_config",
    "app_capability_enabled",
    "credential_capability_enabled",
)


def credential_capability_enabled(principal: object, capability: str) -> bool:
    capabilities = getattr(principal, "capabilities", frozenset())
    return isinstance(capabilities, (set, frozenset)) and capability in capabilities


def app_capability_enabled(app_id: int, capability: str) -> bool:
    # 无行或 enabled=False 均视为关闭。
    return AppCapability.objects.filter(
        app_id=app_id,
        capability=capability,
        enabled=True,
    ).exists()


def app_capability_config(app_id: int, capability: str) -> dict[str, JsonValue]:
    # 无行或空 config 表示全部取 settings 级默认值(由调用方解释)。
    row = (
        AppCapability.objects.filter(app_id=app_id, capability=capability)
        .values_list("config", flat=True)
        .first()
    )
    if not isinstance(row, dict):
        return {}
    return cast("dict[str, JsonValue]", row)

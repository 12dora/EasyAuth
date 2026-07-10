from __future__ import annotations

from collections.abc import Iterable
from typing import Final, cast

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from easyauth.connectors.base import BaseConnector

CONNECTOR_CLASS_INVALID_TEMPLATE: Final = (
    "EASYAUTH_CONNECTORS 中的 {path} 不是 BaseConnector 子类。"
)


def available_connectors() -> dict[str, BaseConnector]:
    """按 settings.EASYAUTH_CONNECTORS 声明顺序实例化全部连接器类型(key → 实例)。

    只支持显式 dotted-path 注册, 不做 entry_points 自动发现(隐式加载不利于审计,
    方案 §3.4)。新增连接器 = 新增实现类 + 一行配置, 零核心代码改动。
    """
    connectors: dict[str, BaseConnector] = {}
    for path in _configured_paths():
        connector_class = cast("object", import_string(path))
        if not (isinstance(connector_class, type) and issubclass(connector_class, BaseConnector)):
            raise ImproperlyConfigured(CONNECTOR_CLASS_INVALID_TEMPLATE.format(path=path))
        connector = connector_class()
        connectors[connector.key] = connector
    return connectors


def get_connector(key: str) -> BaseConnector | None:
    return available_connectors().get(key)


def _configured_paths() -> tuple[str, ...]:
    configured: object = getattr(settings, "EASYAUTH_CONNECTORS", ())
    if isinstance(configured, str):
        return tuple(part.strip() for part in configured.split(",") if part.strip())
    if isinstance(configured, Iterable):
        iterable_paths = cast("Iterable[object]", configured)
        return tuple(item for item in iterable_paths if isinstance(item, str) and item)
    return ()

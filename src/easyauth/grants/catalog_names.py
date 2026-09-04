from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from easyauth.applications.models import AppScope, Permission

if TYPE_CHECKING:
    from collections.abc import Collection

__all__: Final = (
    "CatalogDisplayName",
    "GrantCatalogNames",
    "resolve_catalog_display_names",
)


@dataclass(frozen=True, slots=True)
class CatalogDisplayName:
    name: str
    name_en: str


@dataclass(frozen=True, slots=True)
class GrantCatalogNames:
    permissions: dict[str, CatalogDisplayName]
    scopes: dict[str, CatalogDisplayName]


def resolve_catalog_display_names(
    *,
    app_id: int,
    permission_keys: Collection[str],
    scope_keys: Collection[str],
) -> GrantCatalogNames:
    """按 app 批量解析权限/范围中英文名; 每个模型最多一次查询。

    目录行已不存在时, 中文名回退为 key 本身, 英文名为空字符串。
    这是唯一允许的回退。
    """
    return GrantCatalogNames(
        permissions=_display_names(Permission, app_id=app_id, keys=permission_keys),
        scopes=_display_names(AppScope, app_id=app_id, keys=scope_keys),
    )


def _display_names(
    model: type[Permission | AppScope],
    *,
    app_id: int,
    keys: Collection[str],
) -> dict[str, CatalogDisplayName]:
    unique_keys = set(keys)
    if not unique_keys:
        return {}
    rows = {
        key: CatalogDisplayName(name=name, name_en=name_en)
        for key, name, name_en in model.objects.filter(
            app_id=app_id,
            key__in=unique_keys,
        ).values_list("key", "name", "name_en")
    }
    return {key: rows.get(key, CatalogDisplayName(name=key, name_en="")) for key in unique_keys}

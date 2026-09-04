from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from easyauth.accounts.models import UserMirror
from easyauth.applications.models import App, AppScope, Permission
from easyauth.grants.catalog_names import CatalogDisplayName, resolve_catalog_display_names
from easyauth.grants.models import AccessGrant, AccessGrantPermission
from easyauth.grants.query import ExpandedGrant, resolve_user_permissions

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

pytestmark = pytest.mark.django_db

_CATALOG_MODEL_QUERIES = 2


def test_resolve_catalog_display_names_uses_catalog_rows() -> None:
    app = _app("catalog-names-hit")
    _ = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        name_en="View invoices",
        supported_scopes=["SELF"],
    )
    _ = AppScope.objects.create(app=app, key="SELF", name="本人", name_en="Self")

    catalog = resolve_catalog_display_names(
        app_id=app.id,
        permission_keys=["invoice.read"],
        scope_keys=["SELF"],
    )

    assert catalog.permissions == {
        "invoice.read": CatalogDisplayName(name="查看发票", name_en="View invoices"),
    }
    assert catalog.scopes == {
        "SELF": CatalogDisplayName(name="本人", name_en="Self"),
    }


def test_resolve_catalog_display_names_falls_back_to_key_when_catalog_row_missing() -> None:
    app = _app("catalog-names-missing")
    _ = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        name_en="View invoices",
        supported_scopes=["SELF"],
    )
    _ = AppScope.objects.create(app=app, key="SELF", name="本人", name_en="Self")

    catalog = resolve_catalog_display_names(
        app_id=app.id,
        permission_keys=["invoice.read", "invoice.deleted"],
        scope_keys=["SELF", "REMOVED"],
    )

    assert catalog.permissions["invoice.read"] == CatalogDisplayName(
        name="查看发票",
        name_en="View invoices",
    )
    assert catalog.permissions["invoice.deleted"] == CatalogDisplayName(
        name="invoice.deleted",
        name_en="",
    )
    assert catalog.scopes["SELF"] == CatalogDisplayName(name="本人", name_en="Self")
    assert catalog.scopes["REMOVED"] == CatalogDisplayName(name="REMOVED", name_en="")


def test_resolve_catalog_display_names_keeps_empty_english_name() -> None:
    app = _app("catalog-names-empty-en")
    _ = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        name_en="",
        supported_scopes=["SELF"],
    )
    _ = AppScope.objects.create(app=app, key="SELF", name="本人", name_en="")

    catalog = resolve_catalog_display_names(
        app_id=app.id,
        permission_keys=["invoice.read"],
        scope_keys=["SELF"],
    )

    assert catalog.permissions["invoice.read"].name_en == ""
    assert catalog.scopes["SELF"].name_en == ""


def test_resolve_catalog_display_names_uses_one_query_per_model(
    django_assert_num_queries: Callable[[int], AbstractContextManager[object]],
) -> None:
    app = _app("catalog-names-bulk")
    for index in range(3):
        _ = Permission.objects.create(
            app=app,
            key=f"invoice.read.{index}",
            name=f"查看发票{index}",
            name_en=f"View invoices {index}",
            supported_scopes=["SELF"],
        )
    _ = AppScope.objects.create(app=app, key="SELF", name="本人", name_en="Self")
    _ = AppScope.objects.create(app=app, key="TEAM", name="团队", name_en="Team")
    permission_keys = [f"invoice.read.{index}" for index in range(3)]

    with django_assert_num_queries(_CATALOG_MODEL_QUERIES):
        catalog = resolve_catalog_display_names(
            app_id=app.id,
            permission_keys=permission_keys,
            scope_keys=["SELF", "TEAM"],
        )

    assert len(catalog.permissions) == 3
    assert len(catalog.scopes) == 2


def test_resolve_catalog_display_names_skips_queries_for_empty_keys(
    django_assert_num_queries: Callable[[int], AbstractContextManager[object]],
) -> None:
    app = _app("catalog-names-empty-keys")

    with django_assert_num_queries(0):
        catalog = resolve_catalog_display_names(
            app_id=app.id,
            permission_keys=(),
            scope_keys=(),
        )

    assert catalog.permissions == {}
    assert catalog.scopes == {}


def test_resolve_user_permissions_attaches_catalog_display_names() -> None:
    user = UserMirror.objects.create(authentik_user_id="user-catalog-names-query")
    app = _app("catalog-names-query")
    _ = AppScope.objects.create(app=app, key="SELF", name="本人", name_en="Self")
    permission = Permission.objects.create(
        app=app,
        key="invoice.read",
        name="查看发票",
        name_en="View invoices",
        supported_scopes=["SELF"],
    )
    grant = AccessGrant.objects.create(user=user, app=app)
    _ = AccessGrantPermission.objects.create(
        grant=grant,
        permission=permission,
        scope_key="SELF",
    )

    snapshot = resolve_user_permissions(user=user, app=app)

    expanded = snapshot.grants[0]
    assert expanded.permission_name == "查看发票"
    assert expanded.permission_name_en == "View invoices"
    assert expanded.scope_name == "本人"
    assert expanded.scope_name_en == "Self"
    assert expanded == ExpandedGrant("invoice.read", "SELF", "direct", "", None)


def _app(suffix: str) -> App:
    return App.objects.create(app_key=f"{suffix}-app", name="目录名称应用")

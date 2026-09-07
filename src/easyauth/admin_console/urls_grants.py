from __future__ import annotations

from django.urls import path

from easyauth.admin_console.direct_grants_api import console_direct_grants
from easyauth.admin_console.grant_catalog_api import console_grant_catalog

GRANT_URLPATTERNS = [
    path("api/v1/grant-catalog", console_grant_catalog, name="console-grant-catalog"),
    path("api/v1/direct-grants", console_direct_grants, name="console-direct-grants"),
]

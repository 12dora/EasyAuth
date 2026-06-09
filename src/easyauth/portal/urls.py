from __future__ import annotations

from django.urls import path

from easyauth.portal.api import (
    portal_access_requests,
    portal_expiring_grants,
    portal_grants,
    portal_request_catalog,
)
from easyauth.portal.views import portal_home, portal_react_route

urlpatterns = [
    path("api/v1/me/grants", portal_grants, name="portal-api-grants"),
    path("api/v1/me/grants/expiring", portal_expiring_grants, name="portal-api-expiring-grants"),
    path(
        "api/v1/me/access-requests",
        portal_access_requests,
        name="portal-api-access-requests",
    ),
    path("api/v1/request-catalog", portal_request_catalog, name="portal-api-request-catalog"),
    path("", portal_home, name="portal-home"),
    path("<path:_portal_path>", portal_react_route, name="portal-react-route"),
]

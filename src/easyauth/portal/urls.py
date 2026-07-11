from __future__ import annotations

from django.urls import path

from easyauth.portal.api import (
    portal_access_request_withdraw,
    portal_access_requests,
    portal_expiring_grants,
    portal_grants,
    portal_request_catalog,
)
from easyauth.portal.approvals_api import (
    portal_approval_approve,
    portal_approval_detail,
    portal_approval_reject,
    portal_approvals,
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
    path(
        "api/v1/me/access-requests/<int:request_id>/withdraw",
        portal_access_request_withdraw,
        name="portal-api-access-request-withdraw",
    ),
    path("api/v1/me/approvals", portal_approvals, name="portal-api-approvals"),
    path(
        "api/v1/me/approvals/<int:request_id>",
        portal_approval_detail,
        name="portal-api-approval-detail",
    ),
    path(
        "api/v1/me/approvals/<int:request_id>/approve",
        portal_approval_approve,
        name="portal-api-approval-approve",
    ),
    path(
        "api/v1/me/approvals/<int:request_id>/reject",
        portal_approval_reject,
        name="portal-api-approval-reject",
    ),
    path("api/v1/request-catalog", portal_request_catalog, name="portal-api-request-catalog"),
    path("", portal_home, name="portal-home"),
    path("<path:_portal_path>", portal_react_route, name="portal-react-route"),
]

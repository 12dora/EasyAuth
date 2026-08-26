from __future__ import annotations

from django.urls import path

from easyauth.admin_console.audit_api import console_audit_logs
from easyauth.admin_console.connectors_api import (
    console_app_connector_detail,
    console_app_connector_external_groups,
    console_app_connector_mappings,
    console_app_connector_reconcile,
    console_app_connector_sync_runs,
    console_app_connector_test,
    console_app_connectors,
)
from easyauth.admin_console.operations_approvals_api import (
    operations_approve_access_request,
    operations_reassign_access_request,
    operations_reject_access_request,
)
from easyauth.admin_console.operations_retry_api import operations_retry_grant
from easyauth.admin_console.webhook_config_api import (
    console_app_webhook_config,
    console_app_webhook_test,
)
from easyauth.admin_console.webhook_deliveries_api import (
    console_app_webhook_deliveries,
    console_app_webhook_delivery_redeliver,
)

INTEGRATION_URLPATTERNS = [
    path(
        "api/v1/apps/<str:app_key>/connectors",
        console_app_connectors,
        name="console-app-connectors",
    ),
    path(
        "api/v1/apps/<str:app_key>/connectors/test",
        console_app_connector_test,
        name="console-app-connector-test",
    ),
    path(
        "api/v1/apps/<str:app_key>/connectors/<int:instance_id>",
        console_app_connector_detail,
        name="console-app-connector-detail",
    ),
    path(
        "api/v1/apps/<str:app_key>/connectors/<int:instance_id>/external-groups",
        console_app_connector_external_groups,
        name="console-app-connector-external-groups",
    ),
    path(
        "api/v1/apps/<str:app_key>/connectors/<int:instance_id>/mappings",
        console_app_connector_mappings,
        name="console-app-connector-mappings",
    ),
    path(
        "api/v1/apps/<str:app_key>/connectors/<int:instance_id>/reconcile",
        console_app_connector_reconcile,
        name="console-app-connector-reconcile",
    ),
    path(
        "api/v1/apps/<str:app_key>/connectors/<int:instance_id>/sync-runs",
        console_app_connector_sync_runs,
        name="console-app-connector-sync-runs",
    ),
    path(
        "api/v1/apps/<str:app_key>/webhook-config",
        console_app_webhook_config,
        name="console-app-webhook-config",
    ),
    path(
        "api/v1/apps/<str:app_key>/webhook-config/test",
        console_app_webhook_test,
        name="console-app-webhook-test",
    ),
    path(
        "api/v1/apps/<str:app_key>/webhook-deliveries",
        console_app_webhook_deliveries,
        name="console-app-webhook-deliveries",
    ),
    path(
        "api/v1/apps/<str:app_key>/webhook-deliveries/<int:delivery_pk>/redeliver",
        console_app_webhook_delivery_redeliver,
        name="console-app-webhook-delivery-redeliver",
    ),
    path(
        "api/v1/operations/access-requests/<int:request_id>/retry-grant",
        operations_retry_grant,
        name="operations-retry-grant",
    ),
    path(
        "api/v1/operations/access-requests/<int:request_id>/approve",
        operations_approve_access_request,
        name="operations-approve-access-request",
    ),
    path(
        "api/v1/operations/access-requests/<int:request_id>/reject",
        operations_reject_access_request,
        name="operations-reject-access-request",
    ),
    path(
        "api/v1/operations/access-requests/<int:request_id>/reassign",
        operations_reassign_access_request,
        name="operations-reassign-access-request",
    ),
    path("api/v1/audit-logs", console_audit_logs, name="console-audit-logs"),
]

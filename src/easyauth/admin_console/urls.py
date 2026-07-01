from __future__ import annotations

from django.urls import path

from easyauth.admin_console import views
from easyauth.admin_console.approval_rules_api import (
    console_approval_rule_detail,
    console_approval_rules,
)
from easyauth.admin_console.apps_api import (
    console_app_configuration_status,
    console_app_detail,
    console_apps,
)
from easyauth.admin_console.audit_api import console_audit_logs
from easyauth.admin_console.authorization_groups_api import (
    console_authorization_group_detail,
    console_authorization_groups,
)
from easyauth.admin_console.console_app_api import (
    integration_guide_api,
)
from easyauth.admin_console.credentials_api import (
    console_credentials,
    console_oauth_client_create,
    console_static_token_create,
    console_static_token_rotate,
)
from easyauth.admin_console.credentials_disable_api import (
    console_credential_disable,
    console_static_token_disable,
)
from easyauth.admin_console.memberships_api import (
    console_app_membership_detail,
    console_app_memberships,
)
from easyauth.admin_console.operations_api import (
    operations_access_grants,
    operations_access_requests,
    operations_dependency_health,
    operations_emergency_revokes,
)
from easyauth.admin_console.operations_retry_api import operations_retry_grant
from easyauth.admin_console.permission_catalog_api import (
    console_permission_tree,
    console_role_permission_matrix,
)
from easyauth.admin_console.permission_groups_api import (
    console_permission_group_detail,
    console_permission_groups,
)
from easyauth.admin_console.permission_template_api import (
    app_manifest_api,
    permission_template_confirm_api,
    permission_template_preview_api,
    permission_template_versions_api,
)
from easyauth.admin_console.permissions_api import console_permission_detail, console_permissions
from easyauth.admin_console.query_test_api import console_permission_query_test
from easyauth.admin_console.roles_api import console_role_detail, console_roles
from easyauth.admin_console.scopes_api import console_scope_detail, console_scopes

app_name = "admin_console"

urlpatterns = [
    path("", views.console_home, name="console-home"),
    path("api/v1/apps", console_apps, name="console-apps"),
    path(
        "api/v1/apps/<str:app_key>/configuration-status",
        console_app_configuration_status,
        name="console-app-configuration-status",
    ),
    path(
        "api/v1/apps/<str:app_key>/permission-query-tests",
        console_permission_query_test,
        name="console-permission-query-test",
    ),
    path(
        "api/v1/apps/<str:app_key>/memberships",
        console_app_memberships,
        name="console-app-memberships",
    ),
    path(
        "api/v1/apps/<str:app_key>/memberships/<int:membership_id>",
        console_app_membership_detail,
        name="console-app-membership-detail",
    ),
    path("api/v1/apps/<str:app_key>", console_app_detail, name="console-app-detail"),
    path(
        "api/v1/operations/access-requests",
        operations_access_requests,
        name="operations-access-requests",
    ),
    path(
        "api/v1/operations/access-grants",
        operations_access_grants,
        name="operations-access-grants",
    ),
    path(
        "api/v1/operations/emergency-revokes",
        operations_emergency_revokes,
        name="operations-emergency-revokes",
    ),
    path(
        "api/v1/operations/dependency-health",
        operations_dependency_health,
        name="operations-dependency-health",
    ),
    path(
        "api/v1/operations/access-requests/<int:request_id>/retry-grant",
        operations_retry_grant,
        name="operations-retry-grant",
    ),
    path("api/v1/audit-logs", console_audit_logs, name="console-audit-logs"),
    path(
        "api/v1/apps/<str:app_key>/permission-template-imports/preview",
        permission_template_preview_api,
        name="permission-template-preview-api",
    ),
    path(
        "api/v1/apps/<str:app_key>/permission-template-imports/<str:preview_id>/confirm",
        permission_template_confirm_api,
        name="permission-template-confirm-api",
    ),
    path(
        "api/v1/apps/<str:app_key>/permission-template-versions",
        permission_template_versions_api,
        name="permission-template-versions-api",
    ),
    path(
        "api/v1/apps/<str:app_key>/manifest",
        app_manifest_api,
        name="app-manifest-api",
    ),
    path(
        "api/v1/apps/<str:app_key>/permission-tree",
        console_permission_tree,
        name="console-permission-tree",
    ),
    path(
        "api/v1/apps/<str:app_key>/permission-groups",
        console_permission_groups,
        name="console-permission-groups",
    ),
    path(
        "api/v1/apps/<str:app_key>/permission-groups/<str:group_key>",
        console_permission_group_detail,
        name="console-permission-group-detail",
    ),
    path("api/v1/apps/<str:app_key>/roles", console_roles, name="console-roles"),
    path(
        "api/v1/apps/<str:app_key>/roles/<str:role_key>",
        console_role_detail,
        name="console-role-detail",
    ),
    path("api/v1/apps/<str:app_key>/scopes", console_scopes, name="console-scopes"),
    path(
        "api/v1/apps/<str:app_key>/scopes/<str:scope_key>",
        console_scope_detail,
        name="console-scope-detail",
    ),
    path(
        "api/v1/apps/<str:app_key>/authorization-groups",
        console_authorization_groups,
        name="console-authorization-groups",
    ),
    path(
        "api/v1/apps/<str:app_key>/authorization-groups/<str:authorization_group_key>",
        console_authorization_group_detail,
        name="console-authorization-group-detail",
    ),
    path(
        "api/v1/apps/<str:app_key>/permissions",
        console_permissions,
        name="console-permissions",
    ),
    path(
        "api/v1/apps/<str:app_key>/permissions/<str:permission_key>",
        console_permission_detail,
        name="console-permission-detail",
    ),
    path(
        "api/v1/apps/<str:app_key>/role-permission-matrix",
        console_role_permission_matrix,
        name="console-role-permission-matrix",
    ),
    path(
        "api/v1/apps/<str:app_key>/approval-rules",
        console_approval_rules,
        name="console-approval-rules",
    ),
    path(
        "api/v1/apps/<str:app_key>/approval-rules/<int:approval_rule_id>",
        console_approval_rule_detail,
        name="console-approval-rule-detail",
    ),
    path(
        "api/v1/apps/<str:app_key>/integration-guide",
        integration_guide_api,
        name="integration-guide-api",
    ),
    path(
        "api/v1/apps/<str:app_key>/credentials",
        console_credentials,
        name="console-credentials",
    ),
    path(
        "api/v1/apps/<str:app_key>/credentials/static-tokens",
        console_static_token_create,
        name="console-static-token-create",
    ),
    path(
        "api/v1/apps/<str:app_key>/credentials/static-tokens/<int:credential_id>/rotate",
        console_static_token_rotate,
        name="console-static-token-rotate",
    ),
    path(
        "api/v1/apps/<str:app_key>/credentials/<str:credential_type>/<int:credential_id>/disable",
        console_credential_disable,
        name="console-credential-disable",
    ),
    path(
        "api/v1/apps/<str:app_key>/credentials/static-tokens/<int:credential_id>/disable",
        console_static_token_disable,
        name="console-static-token-disable",
    ),
    path(
        "api/v1/apps/<str:app_key>/credentials/oauth-clients",
        console_oauth_client_create,
        name="console-oauth-client-create",
    ),
    path("operations/", views.console_operations, name="console-operations"),
    path("operations/<path:_path>", views.console_operations, name="console-operations-path"),
    path("apps/<str:app_key>/", views.app_detail, name="app-detail"),
]

from __future__ import annotations

from django.urls import path

from easyauth.admin_console.approval_rules_api import (
    console_approval_rule_detail,
    console_approval_rules,
)
from easyauth.admin_console.authorization_groups_api import (
    console_authorization_group_detail,
    console_authorization_groups,
)
from easyauth.admin_console.console_app_api import integration_guide_api
from easyauth.admin_console.credentials_api import (
    console_credential_capabilities,
    console_credentials,
    console_oauth_client_create,
    console_static_token_create,
    console_static_token_rotate,
)
from easyauth.admin_console.credentials_disable_api import (
    console_credential_disable,
    console_static_token_disable,
)
from easyauth.admin_console.permission_catalog_api import console_permission_tree
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
from easyauth.admin_console.permissions_api import (
    console_permission_detail,
    console_permissions,
)
from easyauth.admin_console.scopes_api import (
    console_scope_detail,
    console_scopes,
)

CATALOG_URLPATTERNS = [
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
        "api/v1/apps/<str:app_key>/credentials/<str:credential_type>/<int:credential_id>/capabilities",
        console_credential_capabilities,
        name="console-credential-capabilities",
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
]


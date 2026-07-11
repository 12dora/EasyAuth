from __future__ import annotations

from django.urls import path

from easyauth.admin_console import views
from easyauth.admin_console.approval_instances_api import (
    operations_approval_instance_redeliver,
    operations_approval_instances,
)
from easyauth.admin_console.approval_rules_api import (
    console_approval_rule_detail,
    console_approval_rules,
)
from easyauth.admin_console.approval_templates_api import (
    console_approval_template_detail,
    console_approval_template_test,
    console_approval_templates,
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
from easyauth.admin_console.auto_onboarding_api import console_app_auto_onboarding
from easyauth.admin_console.connectors_api import (
    console_app_connector_detail,
    console_app_connector_external_groups,
    console_app_connector_mappings,
    console_app_connector_reconcile,
    console_app_connector_sync_runs,
    console_app_connector_test,
    console_app_connectors,
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
from easyauth.admin_console.lifecycle_api import (
    lifecycle_action_operation,
    lifecycle_grant_diff,
    lifecycle_grant_diff_confirm,
    lifecycle_grant_items,
    lifecycle_handover_task_detail,
    lifecycle_handover_tasks,
    lifecycle_onboard,
    lifecycle_onboarding_template_detail,
    lifecycle_onboarding_templates,
    lifecycle_team_item_detail,
)
from easyauth.admin_console.managed_scope_policy_api import console_managed_scope_policy
from easyauth.admin_console.managed_users_preview_api import console_managed_users_preview
from easyauth.admin_console.memberships_api import (
    console_app_membership_detail,
    console_app_memberships,
)
from easyauth.admin_console.operations_api import (
    operations_access_grants,
    operations_access_requests,
    operations_dependency_health,
    operations_dependency_health_check,
    operations_emergency_revokes,
)
from easyauth.admin_console.operations_approvals_api import (
    operations_approve_access_request,
    operations_reassign_access_request,
    operations_reject_access_request,
)
from easyauth.admin_console.operations_retry_api import operations_retry_grant
from easyauth.admin_console.permission_catalog_api import (
    console_permission_tree,
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
from easyauth.admin_console.scopes_api import console_scope_detail, console_scopes
from easyauth.admin_console.settings_api import (
    console_dingtalk_connectivity_test,
    console_integration_settings,
)
from easyauth.admin_console.teams_api import (
    console_team_detail,
    console_team_member_detail,
    console_team_members,
    console_teams,
)
from easyauth.admin_console.two_factor_api import (
    passkey_delete as two_factor_passkey_delete,
)
from easyauth.admin_console.two_factor_api import (
    passkey_register_begin as two_factor_passkey_register_begin,
)
from easyauth.admin_console.two_factor_api import (
    passkey_register_complete as two_factor_passkey_register_complete,
)
from easyauth.admin_console.two_factor_api import (
    totp_begin as two_factor_totp_begin,
)
from easyauth.admin_console.two_factor_api import (
    totp_confirm as two_factor_totp_confirm,
)
from easyauth.admin_console.two_factor_api import (
    totp_disable as two_factor_totp_disable,
)
from easyauth.admin_console.two_factor_api import (
    two_factor_status,
)
from easyauth.admin_console.users_api import console_user_options, console_users
from easyauth.admin_console.webhook_config_api import (
    console_app_webhook_config,
    console_app_webhook_test,
)
from easyauth.admin_console.webhook_deliveries_api import (
    console_app_webhook_deliveries,
    console_app_webhook_delivery_redeliver,
)

app_name = "admin_console"

urlpatterns = [
    path("", views.console_home, name="console-home"),
    path("api/v1/apps", console_apps, name="console-apps"),
    path(
        "api/v1/apps/auto-onboarding",
        console_app_auto_onboarding,
        name="console-app-auto-onboarding",
    ),
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
    path(
        "api/v1/apps/<str:app_key>/managed-scope-policy",
        console_managed_scope_policy,
        name="console-managed-scope-policy",
    ),
    path(
        "api/v1/apps/<str:app_key>/managed-users-preview",
        console_managed_users_preview,
        name="console-managed-users-preview",
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
        "api/v1/operations/dependency-health/checks",
        operations_dependency_health_check,
        name="operations-dependency-health-check",
    ),
    path("api/v1/users", console_users, name="console-users"),
    path("api/v1/user-options", console_user_options, name="console-user-options"),
    path(
        "api/v1/lifecycle/handover-tasks",
        lifecycle_handover_tasks,
        name="lifecycle-handover-tasks",
    ),
    path(
        "api/v1/lifecycle/handover-tasks/<int:task_id>",
        lifecycle_handover_task_detail,
        name="lifecycle-handover-task-detail",
    ),
    path(
        "api/v1/lifecycle/handover-tasks/<int:task_id>/grant-items",
        lifecycle_grant_items,
        name="lifecycle-grant-items",
    ),
    path(
        "api/v1/lifecycle/handover-tasks/<int:task_id>/actions/<str:app_key>/<str:operation>",
        lifecycle_action_operation,
        name="lifecycle-action-operation",
    ),
    path(
        "api/v1/lifecycle/handover-tasks/<int:task_id>/team-items/<int:item_id>",
        lifecycle_team_item_detail,
        name="lifecycle-team-item-detail",
    ),
    path(
        "api/v1/lifecycle/handover-tasks/<int:task_id>/grant-diff",
        lifecycle_grant_diff,
        name="lifecycle-grant-diff",
    ),
    path(
        "api/v1/lifecycle/handover-tasks/<int:task_id>/grant-diff/confirm",
        lifecycle_grant_diff_confirm,
        name="lifecycle-grant-diff-confirm",
    ),
    path(
        "api/v1/lifecycle/onboarding-templates",
        lifecycle_onboarding_templates,
        name="lifecycle-onboarding-templates",
    ),
    path(
        "api/v1/lifecycle/onboarding-templates/<int:template_id>",
        lifecycle_onboarding_template_detail,
        name="lifecycle-onboarding-template-detail",
    ),
    path("api/v1/lifecycle/onboard", lifecycle_onboard, name="lifecycle-onboard"),
    path("api/v1/teams", console_teams, name="console-teams"),
    path("api/v1/teams/<int:team_id>", console_team_detail, name="console-team-detail"),
    path(
        "api/v1/teams/<int:team_id>/members",
        console_team_members,
        name="console-team-members",
    ),
    path(
        "api/v1/teams/<int:team_id>/members/<int:member_id>",
        console_team_member_detail,
        name="console-team-member-detail",
    ),
    path(
        "api/v1/security/two-factor",
        two_factor_status,
        name="console-two-factor-status",
    ),
    path(
        "api/v1/security/two-factor/totp/begin",
        two_factor_totp_begin,
        name="console-two-factor-totp-begin",
    ),
    path(
        "api/v1/security/two-factor/totp/confirm",
        two_factor_totp_confirm,
        name="console-two-factor-totp-confirm",
    ),
    path(
        "api/v1/security/two-factor/totp/disable",
        two_factor_totp_disable,
        name="console-two-factor-totp-disable",
    ),
    path(
        "api/v1/security/two-factor/passkeys/register/begin",
        two_factor_passkey_register_begin,
        name="console-two-factor-passkey-register-begin",
    ),
    path(
        "api/v1/security/two-factor/passkeys/register/complete",
        two_factor_passkey_register_complete,
        name="console-two-factor-passkey-register-complete",
    ),
    path(
        "api/v1/security/two-factor/passkeys/<int:passkey_id>",
        two_factor_passkey_delete,
        name="console-two-factor-passkey-delete",
    ),
    path(
        "api/v1/settings/integrations",
        console_integration_settings,
        name="console-integration-settings",
    ),
    path(
        "api/v1/settings/integrations/dingtalk/test",
        console_dingtalk_connectivity_test,
        name="console-dingtalk-connectivity-test",
    ),
    path(
        "api/v1/approval-templates",
        console_approval_templates,
        name="console-approval-templates",
    ),
    path(
        "api/v1/approval-templates/<int:template_id>",
        console_approval_template_detail,
        name="console-approval-template-detail",
    ),
    path(
        "api/v1/approval-templates/<int:template_id>/test",
        console_approval_template_test,
        name="console-approval-template-test",
    ),
    path(
        "api/v1/operations/approval-instances",
        operations_approval_instances,
        name="operations-approval-instances",
    ),
    path(
        "api/v1/operations/approval-instances/<str:instance_id>/redeliver",
        operations_approval_instance_redeliver,
        name="operations-approval-instance-redeliver",
    ),
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
        "api/v1/apps/<str:app_key>/credentials/static-tokens/<int:credential_id>/disable",
        console_static_token_disable,
        name="console-static-token-disable",
    ),
    path(
        "api/v1/apps/<str:app_key>/credentials/oauth-clients",
        console_oauth_client_create,
        name="console-oauth-client-create",
    ),
    path("operations", views.console_operations, name="console-operations-no-slash"),
    path("operations/", views.console_operations, name="console-operations"),
    path("operations/<path:_path>", views.console_operations, name="console-operations-path"),
    path("settings", views.console_home, name="console-settings"),
    path("settings/", views.console_home, name="console-settings-slash"),
    path("apps/new", views.console_home, name="console-app-new"),
    path("apps/new/", views.console_home, name="console-app-new-slash"),
    path("teams", views.console_home, name="console-teams-page"),
    path("teams/", views.console_home, name="console-teams-page-slash"),
    path("teams/<path:_path>", views.console_operations, name="console-teams-path"),
    path("people", views.console_home, name="console-people"),
    path("people/", views.console_home, name="console-people-slash"),
    path(
        "lifecycle/handover-tasks",
        views.console_home,
        name="console-handover-tasks",
    ),
    path(
        "lifecycle/handover-tasks/",
        views.console_home,
        name="console-handover-tasks-slash",
    ),
    path(
        "lifecycle/handover-tasks/<path:_path>",
        views.console_operations,
        name="console-handover-tasks-path",
    ),
    path(
        "lifecycle/onboarding",
        views.console_home,
        name="console-lifecycle-onboarding",
    ),
    path(
        "lifecycle/onboarding/",
        views.console_home,
        name="console-lifecycle-onboarding-slash",
    ),
    path(
        "approval-templates",
        views.console_home,
        name="console-approval-templates-page",
    ),
    path(
        "approval-templates/",
        views.console_home,
        name="console-approval-templates-page-slash",
    ),
    path("apps/<str:app_key>", views.app_detail, name="app-detail-no-slash"),
    path("apps/<str:app_key>/", views.app_detail, name="app-detail"),
]

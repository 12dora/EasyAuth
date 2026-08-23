from __future__ import annotations

from django.urls import path

from easyauth.admin_console import views
from easyauth.admin_console.app_capability_api import (
    console_app_capabilities,
    console_app_capability_detail,
)
from easyauth.admin_console.apps_api import (
    console_app_configuration_status,
    console_app_detail,
    console_apps,
)
from easyauth.admin_console.auto_onboarding_api import console_app_auto_onboarding
from easyauth.admin_console.managed_scope_policy_api import console_managed_scope_policy
from easyauth.admin_console.managed_users_preview_api import console_managed_users_preview
from easyauth.admin_console.memberships_api import (
    console_app_membership_detail,
    console_app_memberships,
)
from easyauth.admin_console.notification_channel_api import (
    console_app_notification_channel,
    console_app_notification_channel_test,
)
from easyauth.admin_console.operations_api import (
    operations_access_grants,
    operations_access_requests,
    operations_dependency_health,
    operations_dependency_health_check,
    operations_emergency_revokes,
)
from easyauth.admin_console.query_test_api import console_permission_query_test
from easyauth.admin_console.users_api import (
    console_user_options,
    console_users,
)

CORE_URLPATTERNS = [
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
        "api/v1/apps/<str:app_key>/capabilities",
        console_app_capabilities,
        name="console-app-capabilities",
    ),
    path(
        "api/v1/apps/<str:app_key>/capabilities/<str:capability>",
        console_app_capability_detail,
        name="console-app-capability-detail",
    ),
    path(
        "api/v1/apps/<str:app_key>/notification-channel",
        console_app_notification_channel,
        name="console-app-notification-channel",
    ),
    path(
        "api/v1/apps/<str:app_key>/notification-channel/test",
        console_app_notification_channel_test,
        name="console-app-notification-channel-test",
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
]


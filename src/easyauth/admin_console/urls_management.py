from __future__ import annotations

from django.urls import path

from easyauth.admin_console.approval_instances_api import (
    operations_approval_instance_redeliver,
    operations_approval_instances,
)
from easyauth.admin_console.approval_templates_api import (
    console_approval_template_detail,
    console_approval_template_test,
    console_approval_templates,
)
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
from easyauth.admin_console.two_factor_api import passkey_delete as two_factor_passkey_delete
from easyauth.admin_console.two_factor_api import (
    passkey_register_begin as two_factor_passkey_register_begin,
)
from easyauth.admin_console.two_factor_api import (
    passkey_register_complete as two_factor_passkey_register_complete,
)
from easyauth.admin_console.two_factor_api import totp_begin as two_factor_totp_begin
from easyauth.admin_console.two_factor_api import totp_confirm as two_factor_totp_confirm
from easyauth.admin_console.two_factor_api import totp_disable as two_factor_totp_disable
from easyauth.admin_console.two_factor_api import two_factor_status

MANAGEMENT_URLPATTERNS = [
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
]


"""提供应用模型与常量的正式公共入口, 完整再导出各职责模块符号。"""

from easyauth.applications.credential_capabilities import (
    CAPABILITY_DIRECTORY as CAPABILITY_DIRECTORY,
)
from easyauth.applications.credential_capabilities import (
    CAPABILITY_NOTIFY as CAPABILITY_NOTIFY,
)
from easyauth.applications.credential_capabilities import (
    CAPABILITY_VALUES as CAPABILITY_VALUES,
)
from easyauth.applications.integration_settings import IntegrationSettings as IntegrationSettings
from easyauth.applications.oauth_models import OAuthClientBinding as OAuthClientBinding
from easyauth.applications.ops_models import AppMembership as AppMembership
from easyauth.applications.ops_models import (
    AuthorizationGroupAccessPolicy as AuthorizationGroupAccessPolicy,
)
from easyauth.applications.ops_models import PermissionGroup as PermissionGroup
from easyauth.applications.ops_models import (
    PermissionTemplateVersion as PermissionTemplateVersion,
)

from . import constants as _constants
from .app import App as App
from .app import AppCapability as AppCapability
from .app import AppNotificationChannel as AppNotificationChannel
from .approval import ApprovalRule as ApprovalRule
from .catalog import AppScope as AppScope
from .catalog import AuthorizationGroup as AuthorizationGroup
from .catalog import AuthorizationGroupGrant as AuthorizationGroupGrant
from .catalog import Permission as Permission
from .constants import APP_SCOPE_KEY_PATTERN as APP_SCOPE_KEY_PATTERN
from .constants import AUTHORIZATION_GROUP_KINDS as AUTHORIZATION_GROUP_KINDS
from .constants import CAPABILITY_CHOICES as CAPABILITY_CHOICES
from .constants import HANDOVER_CAPABILITY_CHOICES as HANDOVER_CAPABILITY_CHOICES
from .constants import HANDOVER_CAPABILITY_DECLARED as HANDOVER_CAPABILITY_DECLARED
from .constants import HANDOVER_CAPABILITY_NONE as HANDOVER_CAPABILITY_NONE
from .constants import (
    HANDOVER_CAPABILITY_UNDECLARED as HANDOVER_CAPABILITY_UNDECLARED,
)
from .constants import HANDOVER_CAPABILITY_VALUES as HANDOVER_CAPABILITY_VALUES
from .constants import (
    MANAGED_SCOPE_POLICY_ACTIVE_RESOLVERS as MANAGED_SCOPE_POLICY_ACTIVE_RESOLVERS,
)
from .constants import (
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED as MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
)
from .constants import (
    MANAGED_SCOPE_POLICY_RESOLVER_EASYAUTH_TEAM as MANAGED_SCOPE_POLICY_RESOLVER_EASYAUTH_TEAM,
)
from .constants import (
    MANAGED_SCOPE_POLICY_RESOLVER_UNION as MANAGED_SCOPE_POLICY_RESOLVER_UNION,
)
from .constants import MANAGED_SCOPE_POLICY_RESOLVERS as MANAGED_SCOPE_POLICY_RESOLVERS
from .constants import (
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS as MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
)
from .constants import (
    MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT as MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
)
from .constants import (
    MANAGED_SCOPE_POLICY_TARGET_TYPES as MANAGED_SCOPE_POLICY_TARGET_TYPES,
)
from .constants import PERMISSION_RISK_LEVELS as PERMISSION_RISK_LEVELS
from .constants import JsonValue as JsonValue
from .credential import APP_CREDENTIAL_STATIC_KIND as APP_CREDENTIAL_STATIC_KIND
from .credential import TOKEN_LOOKUP_REQUIRED_MESSAGE as TOKEN_LOOKUP_REQUIRED_MESSAGE
from .credential import AppCredential as AppCredential
from .managed_scope import ManagedScopePolicy as ManagedScopePolicy

MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN = (
    _constants.MANAGED_SCOPE_POLICY_RESOLVER_DINGTALK_MANAGER_CHAIN
)
MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT = (
    _constants.MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT
)

__all__ = (
    "CAPABILITY_CHOICES",
    "CAPABILITY_DIRECTORY",
    "CAPABILITY_NOTIFY",
    "CAPABILITY_VALUES",
    "HANDOVER_CAPABILITY_CHOICES",
    "HANDOVER_CAPABILITY_DECLARED",
    "HANDOVER_CAPABILITY_NONE",
    "HANDOVER_CAPABILITY_UNDECLARED",
    "HANDOVER_CAPABILITY_VALUES",
    "App",
    "AppCapability",
    "AppCredential",
    "AppMembership",
    "AppNotificationChannel",
    "AppScope",
    "ApprovalRule",
    "AuthorizationGroup",
    "AuthorizationGroupAccessPolicy",
    "AuthorizationGroupGrant",
    "IntegrationSettings",
    "ManagedScopePolicy",
    "OAuthClientBinding",
    "Permission",
    "PermissionGroup",
    "PermissionTemplateVersion",
)

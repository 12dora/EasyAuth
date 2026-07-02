from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from easyauth.applications.managed_scope_policy import ManagedScopePolicyService
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    App,
    AppCredential,
    AppMembership,
    ApprovalRule,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    OAuthClientBinding,
    Permission,
)
from easyauth.applications.services import APP_CREDENTIAL_STATIC_KIND

CONFIGURATION_STATUS_BLOCKING: Final = "blocking"
CONFIGURATION_STATUS_WARNING: Final = "warning"
CONFIGURATION_STATUS_INFO: Final = "info"
CONFIGURATION_STATUS_READY: Final = "ready"

type ConfigurationIssueSeverity = Literal["blocking", "warning", "info"]
type ConfigurationReadinessStatus = Literal["blocking", "warning", "ready"]


@dataclass(frozen=True, slots=True)
class ConfigurationIssue:
    code: str
    severity: ConfigurationIssueSeverity
    message: str
    subject: str = ""


@dataclass(frozen=True, slots=True)
class ConfigurationReadiness:
    status: ConfigurationReadinessStatus
    issues: tuple[ConfigurationIssue, ...]


def configuration_readiness_for_app(app: App) -> ConfigurationReadiness:
    issues = tuple(_blocking_issues(app)) + tuple(_warning_issues(app))
    return ConfigurationReadiness(status=_readiness_status(issues), issues=issues)


def _blocking_issues(app: App) -> list[ConfigurationIssue]:
    issues: list[ConfigurationIssue] = []
    if not app.is_active:
        issues.append(
            _blocking_issue(
                code="app_inactive",
                message="App 已禁用。",
                subject=app.app_key,
            ),
        )
    if not Permission.objects.filter(app=app, is_active=True, deprecated_at__isnull=True).exists():
        issues.append(
            _blocking_issue(
                code="active_permission_missing",
                message="active App 至少需要一个 active Permission。",
            ),
        )
    if not AuthorizationGroup.objects.filter(app=app, is_active=True).exists():
        issues.append(
            _blocking_issue(
                code="active_authorization_group_missing",
                message="active App 至少需要一个 active AuthorizationGroup。",
            ),
        )
    if not AppMembership.objects.filter(app=app, role="owner", is_active=True).exists():
        issues.append(
            _blocking_issue(
                code="active_owner_missing",
                message="active App 至少需要一个 active owner。",
            ),
        )
    if not _has_active_credential(app):
        issues.append(
            _blocking_issue(
                code="active_credential_missing",
                message="active App 至少需要一个 active 静态 token 或 OAuth2 client。",
            ),
        )
    issues.extend(_requestable_authorization_group_issues(app))
    issues.extend(_authorization_group_grant_issues(app))
    issues.extend(_managed_scope_policy_issues(app))
    return issues


def _requestable_authorization_group_issues(app: App) -> list[ConfigurationIssue]:
    issues: list[ConfigurationIssue] = []
    groups = AuthorizationGroup.objects.filter(
        app=app,
        is_active=True,
        requestable=True,
    ).order_by("key")
    for group in groups:
        has_active_rule = ApprovalRule.objects.filter(
            app=app,
            authorization_group=group,
            is_active=True,
        ).exists()
        if not has_active_rule:
            issues.append(
                _blocking_issue(
                    code="requestable_authorization_group_approval_rule_missing",
                    message="requestable AuthorizationGroup 必须存在 active ApprovalRule。",
                    subject=group.key,
                ),
            )
    return issues


def _authorization_group_grant_issues(app: App) -> list[ConfigurationIssue]:
    grants = AuthorizationGroupGrant.objects.filter(
        authorization_group__app=app,
        is_active=True,
    ).select_related("authorization_group", "permission")
    return [
        _blocking_issue(
            code="authorization_group_grant_target_inactive",
            message="AuthorizationGroupGrant 不能指向 inactive 授权组或 Permission。",
            subject=_authorization_group_grant_subject(grant),
        )
        for grant in grants.order_by("authorization_group__key", "permission__key", "scope_key")
        if not grant.authorization_group.is_active or not grant.permission.is_active
    ]


def _authorization_group_grant_subject(grant: AuthorizationGroupGrant) -> str:
    return (
        f"{grant.authorization_group.key}:"
        f"{grant.permission.key}:"
        f"{grant.scope_key}"
    )


def _managed_scope_policy_issues(app: App) -> list[ConfigurationIssue]:
    issues: list[ConfigurationIssue] = []
    app_default = ManagedScopePolicyService.get_app_default_policy(app=app)
    grants = AuthorizationGroupGrant.objects.filter(
        authorization_group__app=app,
        is_active=True,
        scope_key=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    ).select_related("authorization_group", "permission")
    for grant in grants.order_by("authorization_group__key", "permission__key", "id"):
        override = ManagedScopePolicyService.get_grant_override_policy(app=app, grant=grant)
        subject = _authorization_group_grant_subject(grant)
        if override is not None:
            if _managed_scope_policy_disabled(override):
                issues.append(
                    _blocking_issue(
                        code="managed_scope_policy_disabled",
                        message="MANAGED_USERS grant 的 managed scope policy 已禁用。",
                        subject=subject,
                    ),
                )
            continue
        if app_default is None:
            issues.append(
                _blocking_issue(
                    code="managed_scope_app_default_policy_missing",
                    message="MANAGED_USERS grant 缺少 app default managed scope policy。",
                    subject=subject,
                ),
            )
            continue
        if _managed_scope_policy_disabled(app_default):
            issues.append(
                _blocking_issue(
                    code="managed_scope_policy_disabled",
                    message="MANAGED_USERS grant 继承的 app default managed scope policy 已禁用。",
                    subject=subject,
                ),
            )
    return issues


def _managed_scope_policy_disabled(policy: ManagedScopePolicy) -> bool:
    return not policy.enabled or policy.resolver == MANAGED_SCOPE_POLICY_RESOLVER_DISABLED


def _warning_issues(app: App) -> list[ConfigurationIssue]:
    issues: list[ConfigurationIssue] = []
    permissions = Permission.objects.filter(
        app=app,
        is_active=True,
        deprecated_at__isnull=True,
    ).select_related("group")
    for permission in permissions.order_by("key"):
        if not permission.supported_scopes:
            issues.append(
                ConfigurationIssue(
                    code="permission_supported_scopes_missing",
                    severity=CONFIGURATION_STATUS_WARNING,
                    message="active Permission 必须声明 supported_scopes。",
                    subject=permission.key,
                ),
            )
        group = permission.group
        if group is not None and not group.is_active:
            issues.append(
                ConfigurationIssue(
                    code="permission_group_inactive",
                    severity=CONFIGURATION_STATUS_WARNING,
                    message="active Permission 不应归属 inactive PermissionGroup。",
                    subject=permission.key,
                ),
            )
    return issues


def _has_active_credential(app: App) -> bool:
    return (
        AppCredential.objects.filter(
            app=app,
            credential_type=APP_CREDENTIAL_STATIC_KIND,
            is_active=True,
        ).exists()
        or OAuthClientBinding.objects.filter(app=app, is_active=True).exists()
    )


def _blocking_issue(*, code: str, message: str, subject: str = "") -> ConfigurationIssue:
    return ConfigurationIssue(
        code=code,
        severity=CONFIGURATION_STATUS_BLOCKING,
        message=message,
        subject=subject,
    )


def _readiness_status(
    issues: tuple[ConfigurationIssue, ...],
) -> ConfigurationReadinessStatus:
    if any(issue.severity == CONFIGURATION_STATUS_BLOCKING for issue in issues):
        return CONFIGURATION_STATUS_BLOCKING
    if any(issue.severity == CONFIGURATION_STATUS_WARNING for issue in issues):
        return CONFIGURATION_STATUS_WARNING
    return CONFIGURATION_STATUS_READY

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from easyauth.applications.models import (
    App,
    AppCredential,
    ApprovalRule,
    OAuthClientBinding,
    Permission,
    PermissionGroup,
    Role,
    RolePermission,
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
    if not Role.objects.filter(app=app, is_active=True).exists():
        issues.append(
            _blocking_issue(
                code="active_role_missing",
                message="active App 至少需要一个 active Role。",
            ),
        )
    if not _has_active_credential(app):
        issues.append(
            _blocking_issue(
                code="active_credential_missing",
                message="active App 至少需要一个 active 静态 token 或 OAuth2 client。",
            ),
        )
    issues.extend(_requestable_role_issues(app))
    return issues


def _requestable_role_issues(app: App) -> list[ConfigurationIssue]:
    issues: list[ConfigurationIssue] = []
    roles = Role.objects.filter(app=app, is_active=True, requestable=True).order_by("key")
    for role in roles:
        if not ApprovalRule.objects.filter(app=app, role=role, is_active=True).exists():
            issues.append(
                _blocking_issue(
                    code="requestable_role_approval_rule_missing",
                    message="requestable Role 必须存在 active ApprovalRule。",
                    subject=role.key,
                ),
            )
        if not RolePermission.objects.filter(
            role=role,
            permission__is_active=True,
        ).exists():
            issues.append(
                _blocking_issue(
                    code="requestable_role_permission_missing",
                    message="requestable Role 至少需要映射一个 active Permission。",
                    subject=role.key,
                ),
            )
    return issues


def _warning_issues(app: App) -> list[ConfigurationIssue]:
    if not PermissionGroup.objects.filter(app=app, is_active=True).exists():
        return []

    return [
        ConfigurationIssue(
            code="permission_group_missing",
            severity=CONFIGURATION_STATUS_WARNING,
            message="权限模板存在 group 时, active Permission 应归属到 group。",
            subject=permission.key,
        )
        for permission in Permission.objects.filter(app=app, is_active=True, group__isnull=True)
        .order_by("key")
    ]


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

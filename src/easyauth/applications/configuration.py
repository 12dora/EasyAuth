from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, cast

from django.db.models import Count, Model, Q, QuerySet

if TYPE_CHECKING:
    from collections.abc import Iterable

from easyauth.applications.managed_scope_policy import ManagedScopePolicyService
from easyauth.applications.models import (
    MANAGED_SCOPE_POLICY_RESOLVER_DISABLED,
    MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
    MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
    MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
    App,
    AppCredential,
    AppMembership,
    ApprovalRule,
    AppScope,
    AuthorizationGroup,
    AuthorizationGroupGrant,
    ManagedScopePolicy,
    OAuthClientBinding,
    Permission,
)
from easyauth.applications.services import APP_CREDENTIAL_STATIC_KIND
from easyauth.connectors.models import ConnectorInstance

CONFIGURATION_STATUS_BLOCKING: Final = "blocking"
CONFIGURATION_STATUS_WARNING: Final = "warning"
CONFIGURATION_STATUS_INFO: Final = "info"
CONFIGURATION_STATUS_READY: Final = "ready"
ACTIVE_CREDENTIAL_MISSING_MESSAGE: Final = (
    "未接入连接器的 active App 至少需要一个 active 静态 token 或 OAuth2 client。"
)

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


def configuration_readiness_statuses_for_apps(
    apps: Iterable[App],
) -> dict[int, ConfigurationReadinessStatus]:
    app_items = tuple(apps)
    app_ids = tuple(app.id for app in app_items)
    if not app_ids:
        return {}
    blocking_ids = _required_configuration_blocking_app_ids(app_items, app_ids)
    blocking_ids.update(_requestable_group_missing_rule_app_ids(app_ids))
    blocking_ids.update(_invalid_active_grant_app_ids(app_ids))
    blocking_ids.update(_managed_scope_blocking_app_ids(app_ids))
    warning_ids = _permission_warning_app_ids(app_ids)

    return {
        app_id: _summary_status(app_id, blocking_ids=blocking_ids, warning_ids=warning_ids)
        for app_id in app_ids
    }


def _required_configuration_blocking_app_ids(
    apps: tuple[App, ...],
    app_ids: tuple[int, ...],
) -> set[int]:
    blocking_ids = {app.id for app in apps if not app.is_active}

    active_permission_counts = _counts_by_app(
        Permission.objects.filter(
            app_id__in=app_ids,
            is_active=True,
            deprecated_at__isnull=True,
        ),
    )
    active_group_counts = _counts_by_app(
        AuthorizationGroup.objects.filter(app_id__in=app_ids, is_active=True),
    )
    active_owner_counts = _counts_by_app(
        AppMembership.objects.filter(app_id__in=app_ids, role="owner", is_active=True),
    )
    active_static_credential_counts = _counts_by_app(
        AppCredential.objects.filter(
            app_id__in=app_ids,
            credential_type=APP_CREDENTIAL_STATIC_KIND,
            is_active=True,
        ),
    )
    active_oauth_counts = _counts_by_app(
        OAuthClientBinding.objects.filter(app_id__in=app_ids, is_active=True),
    )
    connector_provisioned_ids = _connector_provisioned_app_ids(app_ids)
    for app_id in app_ids:
        if active_permission_counts.get(app_id, 0) == 0:
            blocking_ids.add(app_id)
        if active_group_counts.get(app_id, 0) == 0:
            blocking_ids.add(app_id)
        if active_owner_counts.get(app_id, 0) == 0:
            blocking_ids.add(app_id)
        if (
            app_id not in connector_provisioned_ids
            and active_static_credential_counts.get(app_id, 0) == 0
            and active_oauth_counts.get(app_id, 0) == 0
        ):
            blocking_ids.add(app_id)
    return blocking_ids


def _counts_by_app(queryset: QuerySet[Model]) -> dict[int, int]:
    rows = cast(
        "Iterable[dict[str, int]]",
        queryset.values("app_id").annotate(total=Count("id")),
    )
    return {int(row["app_id"]): int(row["total"]) for row in rows}


def _requestable_group_missing_rule_app_ids(app_ids: tuple[int, ...]) -> set[int]:
    active_rule_group_ids = set(
        ApprovalRule.objects.filter(
            app_id__in=app_ids,
            authorization_group_id__isnull=False,
            is_active=True,
        ).values_list("authorization_group_id", flat=True),
    )
    return set(
        AuthorizationGroup.objects.filter(
            app_id__in=app_ids,
            is_active=True,
            requestable=True,
        )
        .exclude(id__in=active_rule_group_ids)
        .values_list("app_id", flat=True),
    )


def _invalid_active_grant_app_ids(app_ids: tuple[int, ...]) -> set[int]:
    active_scope_keys_by_app: dict[int, set[str]] = {}
    scope_rows = cast(
        "Iterable[tuple[int, str]]",
        AppScope.objects.filter(
            app_id__in=app_ids,
            is_active=True,
        ).values_list("app_id", "key"),
    )
    for app_id, key in scope_rows:
        active_scope_keys_by_app.setdefault(app_id, set()).add(key)
    invalid_ids: set[int] = set(
        AuthorizationGroupGrant.objects.filter(
            authorization_group__app_id__in=app_ids,
            is_active=True,
        )
        .filter(Q(authorization_group__is_active=False) | Q(permission__is_active=False))
        .values_list("authorization_group__app_id", flat=True),
    )
    grant_scope_rows = cast(
        "Iterable[tuple[int, str]]",
        AuthorizationGroupGrant.objects.filter(
            authorization_group__app_id__in=app_ids,
            is_active=True,
        ).values_list("authorization_group__app_id", "scope_key"),
    )
    for app_id, scope_key in grant_scope_rows:
        if scope_key not in active_scope_keys_by_app.get(app_id, set()):
            invalid_ids.add(app_id)
    return invalid_ids


def _managed_scope_blocking_app_ids(app_ids: tuple[int, ...]) -> set[int]:
    app_defaults = {
        policy.app_id: policy
        for policy in ManagedScopePolicy.objects.filter(
            app_id__in=app_ids,
            target_type=MANAGED_SCOPE_POLICY_TARGET_APP_DEFAULT,
        )
    }
    overrides_by_grant_id: dict[int, ManagedScopePolicy] = {}
    for policy in ManagedScopePolicy.objects.filter(
        app_id__in=app_ids,
        target_type=MANAGED_SCOPE_POLICY_TARGET_AUTHORIZATION_GROUP_GRANT,
    ):
        grant_id = cast("int | None", getattr(policy, "authorization_group_grant_id", None))
        if grant_id is not None:
            overrides_by_grant_id[grant_id] = policy
    blocking_ids: set[int] = set()
    grants = cast(
        "Iterable[tuple[int, int]]",
        AuthorizationGroupGrant.objects.filter(
            authorization_group__app_id__in=app_ids,
            is_active=True,
            scope_key=MANAGED_SCOPE_POLICY_SCOPE_MANAGED_USERS,
        ).values_list("id", "authorization_group__app_id"),
    )
    for grant_id, app_id in grants:
        override = overrides_by_grant_id.get(grant_id)
        if override is not None:
            if _managed_scope_policy_disabled(override):
                blocking_ids.add(app_id)
            continue
        app_default = app_defaults.get(app_id)
        if app_default is None or _managed_scope_policy_disabled(app_default):
            blocking_ids.add(app_id)
    return blocking_ids


def _permission_warning_app_ids(app_ids: tuple[int, ...]) -> set[int]:
    warning_ids: set[int] = set()
    permissions = Permission.objects.filter(
        app_id__in=app_ids,
        is_active=True,
        deprecated_at__isnull=True,
    ).select_related("group")
    for permission in permissions:
        if not permission.supported_scopes:
            warning_ids.add(permission.app_id)
        group = permission.group
        if group is not None and not group.is_active:
            warning_ids.add(permission.app_id)
    return warning_ids


def _summary_status(
    app_id: int,
    *,
    blocking_ids: set[int],
    warning_ids: set[int],
) -> ConfigurationReadinessStatus:
    if app_id in blocking_ids:
        return CONFIGURATION_STATUS_BLOCKING
    if app_id in warning_ids:
        return CONFIGURATION_STATUS_WARNING
    return CONFIGURATION_STATUS_READY


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
    if not _has_active_credential(app) and not _is_connector_provisioned(app):
        issues.append(
            _blocking_issue(
                code="active_credential_missing",
                message=ACTIVE_CREDENTIAL_MISSING_MESSAGE,
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
    active_scope_keys = set(
        AppScope.objects.filter(app=app, is_active=True).values_list("key", flat=True),
    )
    issues: list[ConfigurationIssue] = []
    for grant in grants.order_by("authorization_group__key", "permission__key", "scope_key"):
        subject = _authorization_group_grant_subject(grant)
        if not grant.authorization_group.is_active or not grant.permission.is_active:
            issues.append(
                _blocking_issue(
                    code="authorization_group_grant_target_inactive",
                    message="AuthorizationGroupGrant 不能指向 inactive 授权组或 Permission。",
                    subject=subject,
                ),
            )
        if grant.scope_key not in active_scope_keys:
            issues.append(
                _blocking_issue(
                    code="authorization_group_grant_scope_inactive",
                    message="active AuthorizationGroupGrant 必须引用 active AppScope。",
                    subject=subject,
                ),
            )
    return issues


def _authorization_group_grant_subject(grant: AuthorizationGroupGrant) -> str:
    return f"{grant.authorization_group.key}:{grant.permission.key}:{grant.scope_key}"


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


def _is_connector_provisioned(app: App) -> bool:
    return ConnectorInstance.objects.filter(app=app, enabled=True).exists()


def _connector_provisioned_app_ids(app_ids: tuple[int, ...]) -> set[int]:
    return set(
        ConnectorInstance.objects.filter(app_id__in=app_ids, enabled=True).values_list(
            "app_id",
            flat=True,
        ),
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

import type { AuthorizationGroupGrantItem, ManagedScopePolicyItem } from "../../../../lib/domain";
import type { MessageKey } from "../../../../i18n/messages";
import type { Translator } from "../../../../lib/status";

export function isManagedUsersGrant(grant: AuthorizationGroupGrantItem): boolean {
  return grant.scope === "MANAGED_USERS";
}

export function inheritManagedScopePolicy(): ManagedScopePolicyItem {
  return { mode: "inherit", resolver: null, enabled: true };
}

export function managedScopePolicyResolver(policy: ManagedScopePolicyItem | undefined): string {
  if (policy?.mode === "inherit") {
    return "inherit";
  }
  if (policy?.mode === "disabled" || policy?.resolver === "disabled" || policy?.enabled === false) {
    return "disabled";
  }
  const resolver = policy?.resolver;
  if (resolver === "dingtalk_manager_chain" || resolver === "easyauth_team" || resolver === "union") {
    return resolver;
  }
  return "inherit";
}

export function managedScopePolicyFromMode(resolver: string): ManagedScopePolicyItem {
  if (resolver === "dingtalk_manager_chain") {
    return { mode: "override", resolver, enabled: true };
  }
  if (resolver === "easyauth_team" || resolver === "union") {
    return { mode: resolver, resolver, enabled: true };
  }
  if (resolver === "disabled") {
    return { mode: "disabled", resolver: "disabled", enabled: true };
  }
  return inheritManagedScopePolicy();
}

const EFFECTIVE_RESOLVER_LABEL_KEYS: Record<string, MessageKey> = {
  dingtalk_manager_chain: "console.matrix.grant.policy.override",
  easyauth_team: "console.managedScope.option.team",
  union: "console.managedScope.option.union",
  disabled: "console.matrix.grant.policy.disabled",
};

export function managedScopeEffectivePolicyLabel(t: Translator, grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  const resolver = grant.effective_managed_scope_policy?.resolver;
  const labelKey = resolver ? EFFECTIVE_RESOLVER_LABEL_KEYS[resolver] : undefined;
  return labelKey ? t(labelKey) : t("console.matrix.grant.effective.unconfigured");
}

export function managedScopeInheritedFromLabel(t: Translator, grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  if (grant.effective_managed_scope_policy?.inherited_from === "app_default") {
    return t("console.matrix.grant.inheritedFrom.appDefault");
  }
  if (grant.effective_managed_scope_policy?.source === "authorization_group_grant") {
    return t("console.matrix.grant.inheritedFrom.grantOverride");
  }
  return "-";
}

const HEALTH_LABEL_KEYS: Record<string, MessageKey> = {
  healthy: "console.matrix.grant.health.healthy",
  warning: "console.matrix.grant.health.warning",
  blocked: "console.matrix.grant.health.blocked",
  disabled: "console.matrix.grant.policy.disabled",
};

export function managedScopeHealthLabel(t: Translator, grant: AuthorizationGroupGrantItem): string {
  if (!isManagedUsersGrant(grant)) {
    return "-";
  }
  const status = grant.effective_managed_scope_policy?.health_status;
  const labelKey = status ? HEALTH_LABEL_KEYS[status] : undefined;
  if (labelKey) {
    return t(labelKey);
  }
  return grant.effective_managed_scope_policy?.health_message ?? t("console.matrix.grant.health.unconfigured");
}

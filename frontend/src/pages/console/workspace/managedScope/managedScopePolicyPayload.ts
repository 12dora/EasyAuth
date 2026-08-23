import type { MessageKey } from "../../../../i18n/messages";
import type { JsonObject } from "../../../../lib/api";
import type { AppManagedScopePolicyPayload, EffectiveManagedScopePolicyItem } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";

export type ManagedScopeSelection = "unconfigured" | "dingtalk_manager_chain" | "easyauth_team" | "union" | "disabled";
export type ManagedScopeLoadState = "loading" | "error" | "unconfigured" | "configured";

const MANAGED_SCOPE_RESOLVERS = ["dingtalk_manager_chain", "easyauth_team", "union"] as const;

export const MANAGED_SCOPE_OPTIONS: Array<{ value: ManagedScopeSelection; labelKey: MessageKey }> = [
  { value: "unconfigured", labelKey: "console.managedScope.option.unconfigured" },
  { value: "dingtalk_manager_chain", labelKey: "console.managedScope.option.dingtalk" },
  { value: "easyauth_team", labelKey: "console.managedScope.option.team" },
  { value: "union", labelKey: "console.managedScope.option.union" },
  { value: "disabled", labelKey: "console.managedScope.option.disabled" },
];

export function validateManagedScopePolicyPayload(
  payload: unknown,
  invalidResponseMessage: string,
): AppManagedScopePolicyPayload {
  if (
    !isRecord(payload)
    || !("managed_scope_policy" in payload)
    || !("effective_managed_scope_policy" in payload)
    || !isManagedScopePolicySnapshot(payload.managed_scope_policy)
    || !isEffectiveManagedScopePolicySnapshot(payload.effective_managed_scope_policy)
  ) {
    throw new Error(invalidResponseMessage);
  }
  return payload as unknown as AppManagedScopePolicyPayload;
}

function isManagedScopePolicySnapshot(value: unknown): boolean {
  return value === null || (
    isRecord(value)
    && isManagedScopeSnapshotResolver(value.resolver)
    && typeof value.enabled === "boolean"
  );
}

function isEffectiveManagedScopePolicySnapshot(value: unknown): boolean {
  return value === null || (
    isRecord(value)
    && isManagedScopeSnapshotResolver(value.resolver)
    && typeof value.enabled === "boolean"
    && typeof value.source === "string"
    && typeof value.health_status === "string"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isManagedScopeSnapshotResolver(value: unknown): boolean {
  return value === "disabled" || isManagedScopeResolver(value);
}

export function payloadForManagedScopeSelection(selection: ManagedScopeSelection): JsonObject | null {
  if (selection === "unconfigured") {
    return null;
  }
  if (selection === "disabled") {
    return { mode: "disabled", resolver: "disabled", enabled: false };
  }
  return { mode: "override", resolver: selection, enabled: true };
}

function isManagedScopeResolver(value: unknown): value is (typeof MANAGED_SCOPE_RESOLVERS)[number] {
  return MANAGED_SCOPE_RESOLVERS.includes(value as (typeof MANAGED_SCOPE_RESOLVERS)[number]);
}

export function selectionFromManagedScopePayload(payload: AppManagedScopePolicyPayload): ManagedScopeSelection {
  const policy = payload.managed_scope_policy;
  if (!policy) {
    return "unconfigured";
  }
  if (policy.mode === "disabled" || policy.resolver === "disabled" || policy.enabled === false) {
    return "disabled";
  }
  if (isManagedScopeResolver(policy.resolver)) {
    return policy.resolver;
  }
  return "unconfigured";
}

const MANAGED_SCOPE_RESOLVER_LABEL_KEYS: Record<string, MessageKey> = {
  dingtalk_manager_chain: "console.managedScope.option.dingtalk",
  easyauth_team: "console.managedScope.option.team",
  union: "console.managedScope.option.union",
  disabled: "console.managedScope.option.disabled",
};

export function effectiveManagedScopeLabel(t: Translator, policy: EffectiveManagedScopePolicyItem | null): string {
  if (!policy?.resolver) {
    return t("console.managedScope.option.unconfigured");
  }
  const labelKey = MANAGED_SCOPE_RESOLVER_LABEL_KEYS[policy.resolver];
  return labelKey ? t(labelKey) : policy.resolver;
}

export function managedScopeSourceLabel(t: Translator, source: EffectiveManagedScopePolicyItem["source"] | undefined): string {
  if (source === "app_default") {
    return t("console.managedScope.source.appDefault");
  }
  if (source === "authorization_group_grant") {
    return t("console.managedScope.source.grantOverride");
  }
  return t("console.managedScope.source.unconfigured");
}

const MANAGED_SCOPE_HEALTH_LABEL_KEYS: Record<string, MessageKey> = {
  healthy: "console.managedScope.health.healthy",
  warning: "console.managedScope.health.warning",
  blocked: "console.managedScope.health.blocked",
  disabled: "console.managedScope.health.disabled",
};

export function managedScopeHealthLabel(t: Translator, policy: EffectiveManagedScopePolicyItem | null): string {
  const health = policy?.health_status;
  const labelKey = health ? MANAGED_SCOPE_HEALTH_LABEL_KEYS[health] : undefined;
  return labelKey ? t(labelKey) : t("console.managedScope.health.unconfigured");
}

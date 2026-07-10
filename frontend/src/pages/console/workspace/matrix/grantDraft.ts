import type { JsonObject } from "../../../../lib/api";
import type {
  AuthorizationGroupGrantItem,
  AuthorizationGroupItem,
  EffectiveManagedScopePolicyItem,
  ManagedScopePolicyItem,
} from "../../../../lib/domain";

export type AuthorizationGroupGrantPayload = JsonObject & {
  permission: string;
  scope: string;
  is_active: boolean;
  managed_scope_policy?: JsonObject;
};

export interface AuthorizationGroupGrantDraft {
  permission: string;
  scope: string;
  is_active: boolean;
  managed_scope_policy?: ManagedScopePolicyItem;
  effective_managed_scope_policy?: EffectiveManagedScopePolicyItem | null;
}

export interface AuthorizationGroupSavePayload extends JsonObject {
  key: string;
  kind: string;
  name: string;
  description: string;
  requestable: boolean;
  is_active: boolean;
  grants: AuthorizationGroupGrantPayload[];
}

export function createGrantDraft(initialGrants: AuthorizationGroupGrantItem[] = []) {
  let current = normalizeGrants(initialGrants);

  return {
    grants: () => [...current],
    addGrant: (permission: string, scope: string) => {
      if (!permission || !scope || current.some((grant) => sameGrant(grant, permission, scope))) {
        return;
      }
      current = [...current, { permission, scope, is_active: true }];
    },
    removeGrant: (permission: string, scope: string) => {
      current = current.filter((grant) => !sameGrant(grant, permission, scope));
    },
    setGrantActive: (permission: string, scope: string, isActive: boolean) => {
      current = current.map((grant) =>
        sameGrant(grant, permission, scope) ? { ...grant, is_active: isActive } : grant,
      );
    },
  };
}

export function buildAuthorizationGroupPayload(group: AuthorizationGroupItem): AuthorizationGroupSavePayload {
  return {
    key: group.key,
    kind: group.kind,
    name: group.name,
    description: group.description ?? "",
    requestable: group.requestable,
    is_active: group.is_active,
    grants: normalizeGrants(group.grants).map(grantPayload),
  };
}

export function normalizeGrants(grants: AuthorizationGroupGrantItem[]): AuthorizationGroupGrantDraft[] {
  const seen = new Set<string>();
  const normalized: AuthorizationGroupGrantDraft[] = [];
  for (const grant of grants) {
    if (!grant.permission || !grant.scope) {
      continue;
    }
    const key = grantKey(grant.permission, grant.scope);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    normalized.push({
      permission: grant.permission,
      scope: grant.scope,
      is_active: grant.is_active !== false,
      ...(grant.managed_scope_policy ? { managed_scope_policy: normalizeManagedScopePolicy(grant.managed_scope_policy) } : {}),
      ...(grant.effective_managed_scope_policy ? { effective_managed_scope_policy: grant.effective_managed_scope_policy } : {}),
    });
  }
  return normalized;
}

export function grantKey(permission: string, scope: string): string {
  return `${permission}:${scope}`;
}

function sameGrant(grant: AuthorizationGroupGrantItem, permission: string, scope: string): boolean {
  return grant.permission === permission && grant.scope === scope;
}

function grantPayload(grant: AuthorizationGroupGrantDraft): AuthorizationGroupGrantPayload {
  return {
    permission: grant.permission,
    scope: grant.scope,
    is_active: grant.is_active,
    ...(grant.managed_scope_policy ? { managed_scope_policy: managedScopePolicyPayload(grant.managed_scope_policy) } : {}),
  };
}

function normalizeManagedScopePolicy(policy: ManagedScopePolicyItem): ManagedScopePolicyItem {
  return {
    mode: policy.mode,
    ...(policy.resolver !== undefined ? { resolver: policy.resolver } : {}),
    ...(policy.enabled !== undefined ? { enabled: policy.enabled } : {}),
  };
}

function managedScopePolicyPayload(policy: ManagedScopePolicyItem): JsonObject {
  return normalizeManagedScopePolicy(policy) as unknown as JsonObject;
}

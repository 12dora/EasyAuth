import type { Dispatch, SetStateAction } from "react";

import type { AuthorizationGroupGrantItem, AuthorizationGroupItem } from "../../../../lib/domain";
import { grantKey } from "./grantDraft";
import { managedScopePolicyFromMode } from "./managedScopePolicy";

export type AuthorizationGroupForm = AuthorizationGroupItem;

export function updateGrant(
  target: AuthorizationGroupGrantItem,
  isActive: boolean,
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>,
) {
  const targetKey = grantKey(target.permission, target.scope);
  // 基于 updater 的 current.grants 计算, 避免批处理时用到过期快照相互覆盖(与 removeGrant 同一口径)。
  setForm((current) => ({
    ...current,
    grants: current.grants.map((grant) => (grantKey(grant.permission, grant.scope) === targetKey ? { ...grant, is_active: isActive } : grant)),
  }));
}

export function updateGrantManagedScopePolicy(
  target: AuthorizationGroupGrantItem,
  mode: string,
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>,
) {
  const targetKey = grantKey(target.permission, target.scope);
  setForm((current) => ({
    ...current,
    grants: current.grants.map((grant) =>
      grantKey(grant.permission, grant.scope) === targetKey
        ? { ...grant, managed_scope_policy: managedScopePolicyFromMode(mode) }
        : grant,
    ),
  }));
}

export function removeGrant(
  target: AuthorizationGroupGrantItem,
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>,
) {
  const targetKey = grantKey(target.permission, target.scope);
  setForm((current) => ({
    ...current,
    grants: current.grants.filter((grant) => grantKey(grant.permission, grant.scope) !== targetKey),
  }));
}

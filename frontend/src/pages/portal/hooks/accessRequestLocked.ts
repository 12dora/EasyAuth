/**
 * 组织授权下发的锁定目标: 来自当前授权上 source=department 的成员关系。
 *
 * 锁定项在 PermissionSelector 勾选且不可改, 不进申请草稿与提交载荷。
 */

import type { PortalCurrentGrant } from "../../../lib/domain";
import type { PortalGrantRow } from "../portalListPayload";
import { groupCoveredSelectionKeys } from "./accessRequestCatalog";
import { directGrantSelectionKey, uniqueStrings } from "./accessRequestSelection";
import type { CatalogView } from "./accessRequestTypes";

export type PortalCurrentGrantRow = PortalGrantRow & PortalCurrentGrant;

export function departmentSourcedGroupKeys(grant: PortalCurrentGrant): string[] {
  return uniqueStrings(
    grant.authorization_groups.filter((group) => group.source === "department").map((group) => group.key),
  );
}

export function departmentSourcedPermissionKeys(grant: PortalCurrentGrant): string[] {
  return uniqueStrings(
    grant.direct_grants
      .filter((permission) => permission.source === "department")
      .map((permission) => directGrantSelectionKey(permission.permission, permission.scope)),
  );
}

/** 锁定组 key + 锁定直接权限及其组覆盖范围, 交给 PermissionSelector.lockedKeys。 */
export function departmentSourcedLockedKeys(
  grant: PortalCurrentGrant | undefined,
  catalogView: CatalogView,
): { groupKeys: string[]; selectionKeys: string[] } {
  if (!grant) {
    return { groupKeys: [], selectionKeys: [] };
  }
  const groupKeys = departmentSourcedGroupKeys(grant);
  return {
    groupKeys,
    selectionKeys: uniqueStrings([
      ...departmentSourcedPermissionKeys(grant),
      ...groupCoveredSelectionKeys(groupKeys, catalogView),
    ]),
  };
}

/**
 * 从当前授权还原申请草稿时去掉组织授权来源。
 *
 * 有效快照(groups / grants)仍是展示现状的来源; 组织下发的那部分改走锁定态, 不能写进提交载荷。
 */
export function userSourcedDraftFromCurrentGrant(grant: PortalCurrentGrantRow): {
  groupKeys: string[];
  selectionKeys: string[];
} {
  const lockedGroupKeys = new Set(departmentSourcedGroupKeys(grant));
  const lockedPermissionKeys = new Set(departmentSourcedPermissionKeys(grant));
  return {
    groupKeys: grant.groups.map((group) => group.key).filter((key) => !lockedGroupKeys.has(key)),
    selectionKeys: grant.grants
      .filter((item) => item.source_type === "direct")
      .map((item) => directGrantSelectionKey(item.permission, item.scope))
      .filter((key) => !lockedPermissionKeys.has(key)),
  };
}

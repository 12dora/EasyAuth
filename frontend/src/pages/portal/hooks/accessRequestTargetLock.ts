/*
 * 撤销申请对申请目标的收敛口径。
 *
 * 撤销提交出去的目标是"撤销之后保留下来的授权"(application_grants._apply_revoke_request 直接拿它
 * 当新的成员关系), 后端要求它是基础授权的真子集(submission_validation._validate_revoke_subset):
 * 权限组集合与直接权限集合都必须是子集, 并且不能与基础授权完全相等。
 * 因此撤销草稿里只可能出现基础授权已有的东西, 界面上越界的添加入口必须禁用, 动作层再兜一道。
 */

import type { PortalGrantRow } from "../portalListPayload";
import { collectScopedGroupPermissions } from "./accessRequestCatalog";
import { directGrantSelectionKey, nextPermissionScopeSelection } from "./accessRequestSelection";
import type {
  AccessRequestPayloadValues,
  AccessRequestType,
  ScopedPermissionGroupItem,
} from "./accessRequestTypes";

/** 撤销申请的基础授权快照: 与后端 EffectiveGrantSnapshot 的 group_ids / direct_grants 一一对应。 */
export interface RevokeBaseGrantSnapshot {
  groupKeys: string[];
  directSelectionKeys: string[];
}

/** 只有撤销申请受这套收敛约束; 其余申请类型返回 null 表示目标不受基础授权限制。 */
export function revokeBaseGrantSnapshot(
  requestType: AccessRequestType,
  selectedBaseGrant: PortalGrantRow | undefined,
): RevokeBaseGrantSnapshot | null {
  if (requestType !== "revoke" || !selectedBaseGrant) {
    return null;
  }
  return {
    groupKeys: selectedBaseGrant.groups.map((group) => group.key),
    directSelectionKeys: selectedBaseGrant.grants
      .filter((item) => item.source_type === "direct")
      .map((item) => directGrantSelectionKey(item.permission, item.scope)),
  };
}

/**
 * 撤销目标必须真的减少授权。
 *
 * 目标与基础授权完全相等时后端直接拒(revoke request must reduce current grant), 因此这种草稿不能提交。
 * 目标为空是合法的"撤销全部": 空集是非空基础授权的真子集。
 */
export function revokeTargetIsStrictReduction(
  values: AccessRequestPayloadValues,
  snapshot: RevokeBaseGrantSnapshot,
): boolean {
  const groupKeys = new Set(values.authorizationGroupKeys);
  const directKeys = new Set(values.selectedPermissionKeys);
  const snapshotGroupKeys = new Set(snapshot.groupKeys);
  const snapshotDirectKeys = new Set(snapshot.directSelectionKeys);
  if (Array.from(groupKeys).some((key) => !snapshotGroupKeys.has(key))) {
    return false;
  }
  if (Array.from(directKeys).some((key) => !snapshotDirectKeys.has(key))) {
    return false;
  }
  return groupKeys.size < snapshotGroupKeys.size || directKeys.size < snapshotDirectKeys.size;
}

/**
 * 撤销草稿里允许出现的权限范围: 基础授权的直接权限, 加上当前仍选中的权限组覆盖到的范围。
 *
 * 后者必须保持可点——取消其中一项等于把覆盖它的权限组整体移出保留范围, 这是撤销权限组的唯一入口。
 * 返回 null 表示不是撤销申请, 没有越界一说。
 */
export function retainableSelectionKeySet(
  snapshot: RevokeBaseGrantSnapshot | null,
  coveredSelectionKeys: string[],
): Set<string> | null {
  if (snapshot === null) {
    return null;
  }
  return new Set([...snapshot.directSelectionKeys, ...coveredSelectionKeys]);
}

/** 撤销草稿里越界的权限范围: 既不在基础授权里, 也不由当前所选权限组覆盖。 */
export function selectionKeysOutsideRetainableTarget(
  selectionKeys: string[],
  retainableKeySet: Set<string> | null,
): string[] {
  if (retainableKeySet === null) {
    return [];
  }
  return selectionKeys.filter((key) => !retainableKeySet.has(key));
}

/**
 * 权限组表头 chip 点一下是否会添加越界权限。
 *
 * 表头 chip 的"选中"方向会按范围递增关系一路补齐低位范围(见 nextPermissionScopeSelection),
 * 所以要拿真正会落下来的范围集合去比, 不能只看被点的那一个范围。
 * 已经全勾时这一次点击是清空, 算不出任何新增, 因此同一个判断也覆盖了"清空方向不禁用"。
 */
export function groupScopeChipAddsOutsideRetainableTarget(
  group: ScopedPermissionGroupItem,
  scopeKey: string,
  displaySelectedKeys: string[],
  retainableKeySet: Set<string> | null,
): boolean {
  if (retainableKeySet === null) {
    return false;
  }
  const supportedPermissions = collectScopedGroupPermissions(group).filter((permission) =>
    (permission.scopes ?? []).some((scope) => scope.key === scopeKey),
  );
  const nextSelectionKeys = supportedPermissions.reduce(
    (selectionKeys, permission) => nextPermissionScopeSelection(permission, scopeKey, true, selectionKeys),
    displaySelectedKeys,
  );
  const displayKeySet = new Set(displaySelectedKeys);
  return nextSelectionKeys.some((key) => !displayKeySet.has(key) && !retainableKeySet.has(key));
}

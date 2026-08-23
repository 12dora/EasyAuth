import type {
  HandoverAction,
  HandoverAssetAction,
  HandoverAssetItem,
  HandoverAssetType,
  HandoverOverrideEntry,
  HandoverUserRef,
} from "../../lib/domain";

export type DraftOverride = {
  asset_id: string;
  action: HandoverAssetAction;
  to_user: HandoverUserRef | null;
  label: string;
};

/** 条目动作与类型默认完全一致即「非 override」: 改回默认要从草稿集删除, 保存时也不下发。 */
export function matchesTypeDefault(
  entry: Pick<DraftOverride, "action" | "to_user">,
  assetType: HandoverAssetType,
): boolean {
  const sameAction = entry.action === assetType.default_action;
  const sameUser = (entry.to_user?.user_id ?? "") === (assetType.default_to_user?.user_id ?? "");
  return sameAction && (entry.action !== "transfer" || sameUser);
}

export function isStillOverride(entry: DraftOverride, assetType: HandoverAssetType): boolean {
  return !matchesTypeDefault(entry, assetType);
}

/** transfer 无接收人是显式非法草稿: 禁止执行直到 PATCH 落库合法值(02 §6.1) */
export function hasIncompleteTypeTransfer(types: HandoverAssetType[]): boolean {
  return types.some((row) => row.count > 0 && row.default_action === "transfer" && !row.default_to_user?.user_id);
}

export function hasIncompleteTransferDraft(drafts: DraftOverride[]): boolean {
  return drafts.some((entry) => entry.action === "transfer" && !entry.to_user?.user_id);
}

/** 把某个资产类型的默认动作/接收人换成新值, 其余行原样保留。 */
export function withTypeDefault(
  types: HandoverAssetType[],
  type: string,
  nextAction: HandoverAssetAction,
  nextUser: HandoverUserRef | null,
): HandoverAssetType[] {
  return types.map((row) =>
    row.type === type
      ? { ...row, default_action: nextAction, default_to_user: nextAction === "transfer" ? nextUser : null }
      : row,
  );
}

export function replaceAssetType(types: HandoverAssetType[], next: HandoverAssetType): HandoverAssetType[] {
  return types.map((row) => (row.type === next.type ? next : row));
}

export function withOverrideCount(
  types: HandoverAssetType[],
  type: string,
  overrideCount: number,
): HandoverAssetType[] {
  return types.map((row) => (row.type === type ? { ...row, override_count: overrideCount } : row));
}

export function draftsFromOverrides(entries: HandoverOverrideEntry[]): Record<string, DraftOverride> {
  const mapped = entries.map((entry) => ({
    asset_id: entry.asset_id,
    action: entry.action,
    to_user: entry.to_user ?? (entry.to_user_id ? { user_id: entry.to_user_id, name: entry.to_user_id } : null),
    label: entry.label,
  }));
  return Object.fromEntries(mapped.map((entry) => [entry.asset_id, entry]));
}

export function effectiveOverride(
  drafts: Record<string, DraftOverride>,
  item: HandoverAssetItem,
  assetType: HandoverAssetType,
): DraftOverride {
  const draft = drafts[item.id];
  if (draft) {
    return draft;
  }
  return {
    asset_id: item.id,
    action: assetType.default_action,
    to_user: assetType.default_to_user,
    label: item.label,
  };
}

export function mergeItemDraft(
  drafts: Record<string, DraftOverride>,
  item: HandoverAssetItem,
  assetType: HandoverAssetType,
  patch: Partial<DraftOverride>,
): DraftOverride {
  return {
    ...effectiveOverride(drafts, item, assetType),
    ...patch,
    asset_id: item.id,
    label: item.label,
  };
}

/** 改回默认 → 从完整草稿集删除; 不得依赖 fullOverrides 在换页时复活。 */
export function applyItemDraft(
  drafts: Record<string, DraftOverride>,
  merged: DraftOverride,
  assetType: HandoverAssetType,
): Record<string, DraftOverride> {
  const next = { ...drafts };
  if (matchesTypeDefault(merged, assetType)) {
    delete next[merged.asset_id];
  } else {
    next[merged.asset_id] = merged;
  }
  return next;
}

export function buildOverridesBody(drafts: DraftOverride[], assetType: HandoverAssetType) {
  return drafts
    .filter((entry) => isStillOverride(entry, assetType))
    .map((entry) => ({
      asset_id: entry.asset_id,
      action: entry.action,
      to_user_id: entry.action === "transfer" ? (entry.to_user?.user_id ?? null) : null,
      label: entry.label,
    }));
}

/** 供测试与执行确认文案复用 */
export function countArrangedAssetTypes(types: HandoverAssetType[]): { arranged: number; total: number } {
  return {
    arranged: types.filter((row) => row.default_action !== "skip" || row.override_count > 0).length,
    total: types.length,
  };
}

export function buildExecuteConfirmParts(action: HandoverAction): {
  transferLines: string[];
  overrideCount: number;
  uniqueReceiverNames: string[];
} {
  const transferLines: string[] = [];
  const receiverIds = new Set<string>();
  const uniqueReceiverNames: string[] = [];
  let overrideCount = 0;
  for (const assetType of action.asset_types) {
    overrideCount += assetType.override_count;
    if (assetType.default_action === "transfer" && assetType.count > 0) {
      const name = assetType.default_to_user?.name || assetType.default_to_user?.user_id || "";
      transferLines.push(`${assetType.count} ${assetType.label}${name ? ` → ${name}` : ""}`);
      const id = assetType.default_to_user?.user_id;
      if (id && !receiverIds.has(id)) {
        receiverIds.add(id);
        uniqueReceiverNames.push(name || id);
      }
    }
  }
  return { transferLines, overrideCount, uniqueReceiverNames };
}

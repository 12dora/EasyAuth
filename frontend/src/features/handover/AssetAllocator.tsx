import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "../../components/Button";
import { SelectInput, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { apiErrorReason } from "../../lib/apiErrorReason";
import { cn } from "../../lib/cn";
import type {
  HandoverAction,
  HandoverAssetAction,
  HandoverAssetItem,
  HandoverAssetItemsPage,
  HandoverAssetType,
  HandoverOverrideEntry,
  HandoverOverridesPayload,
  HandoverUserRef,
} from "../../lib/domain";
import { HandoverUserPicker } from "./HandoverUserPicker";
import { handoverAssetTypePath, type HandoverSurface } from "./surface";

export interface AssetAllocatorProps {
  surface: HandoverSurface;
  taskId: number | string;
  action: HandoverAction;
  /** executing / async_pending / batch_progress 期间整个分配器只读 */
  readOnly?: boolean;
  onActionUpdated?: (patch: {
    asset_types?: HandoverAssetType[];
    confirm_version?: number;
    overrides_version?: number;
  }) => void;
  /** 保存中时禁用父级 [执行交接] */
  onBusyChange?: (busy: boolean) => void;
  /** 412 snapshot_stale：清单已变，需清本地态并重新预演 */
  onSnapshotStale?: () => void;
}

type DraftOverride = {
  asset_id: string;
  action: HandoverAssetAction;
  to_user: HandoverUserRef | null;
  label: string;
};

export function AssetAllocator({
  surface,
  taskId,
  action,
  readOnly = false,
  onActionUpdated,
  onBusyChange,
  onSnapshotStale,
}: AssetAllocatorProps) {
  const { t } = useI18n();
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [localTypes, setLocalTypes] = useState(action.asset_types);
  const [typeError, setTypeError] = useState<string | null>(null);
  const [savingType, setSavingType] = useState(false);
  const [detailsBusy, setDetailsBusy] = useState(false);

  useEffect(() => {
    setLocalTypes(action.asset_types);
  }, [action.asset_types]);

  useEffect(() => {
    onBusyChange?.(savingType || detailsBusy);
  }, [onBusyChange, savingType, detailsBusy]);

  const arrangedCount = localTypes.filter((row) => row.default_action !== "skip" || row.override_count > 0).length;
  const totalTypes = localTypes.length;

  const patchType = async (
    assetType: HandoverAssetType,
    nextAction: HandoverAssetAction,
    nextUser: HandoverUserRef | null,
  ) => {
    // transfer 必须先本地展示接收人选择器，选中接收人后才 PATCH（01 §5.4 receiver_required）
    if (nextAction === "transfer" && !nextUser) {
      setLocalTypes((current) =>
        current.map((row) =>
          row.type === assetType.type
            ? { ...row, default_action: "transfer", default_to_user: null }
            : row,
        ),
      );
      setTypeError(null);
      return;
    }

    const previous = localTypes;
    const optimistic = localTypes.map((row) =>
      row.type === assetType.type
        ? {
            ...row,
            default_action: nextAction,
            default_to_user: nextAction === "transfer" ? nextUser : null,
          }
        : row,
    );
    setLocalTypes(optimistic);
    setTypeError(null);
    setSavingType(true);
    try {
      const payload = await apiRequest<{ asset_type: HandoverAssetType; confirm_version: number }>(
        handoverAssetTypePath(surface, taskId, action.app_key, assetType.type),
        {
          method: "PATCH",
          body: {
            default_action: nextAction,
            default_to_user_id: nextAction === "transfer" ? (nextUser?.user_id ?? null) : null,
          },
        },
      );
      setLocalTypes((current) =>
        current.map((row) => (row.type === payload.asset_type.type ? payload.asset_type : row)),
      );
      onActionUpdated?.({
        asset_types: localTypes.map((row) =>
          row.type === payload.asset_type.type ? payload.asset_type : row,
        ),
        confirm_version: payload.confirm_version,
      });
    } catch (error) {
      setLocalTypes(previous);
      const reason = apiErrorReason(error);
      if (reason === "snapshot_stale") {
        setTypeError(t("handover.portal.detail.snapshotStale"));
        onSnapshotStale?.();
      } else {
        setTypeError((error as Error).message);
      }
    } finally {
      setSavingType(false);
    }
  };

  return (
    <div className="space-y-3" data-testid="asset-allocator">
      <p className="text-caption text-ink-soft" data-testid="asset-allocator-progress">
        {t("handover.allocator.arranged", { arranged: arrangedCount, total: totalTypes })}
      </p>
      {typeError ? <StatusBanner live="alert" tone="signal" title={typeError} /> : null}
      <ul className="grid gap-2">
        {localTypes.map((assetType) => {
          const isEmpty = assetType.count === 0;
          const isExpanded = expandedType === assetType.type;
          return (
            <li
              key={assetType.type}
              className={cn(
                "rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5",
                isEmpty && "opacity-60",
              )}
              data-testid={`asset-type-row-${assetType.type}`}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="min-w-28 text-body font-medium text-ink">{assetType.label || assetType.type}</span>
                <span className="text-caption text-ink-faint">
                  {t("handover.allocator.count", { count: assetType.count })}
                </span>
                {isEmpty ? (
                  <span className="text-caption text-ink-faint">{t("handover.allocator.noData")}</span>
                ) : (
                  <>
                    <AssetActionSelect
                      value={assetType.default_action}
                      releasable={assetType.releasable}
                      disabled={readOnly || savingType}
                      aria-label={`${assetType.label} ${t("handover.allocator.defaultAction")}`}
                      onChange={(next) => {
                        void patchType(
                          assetType,
                          next,
                          next === "transfer" ? assetType.default_to_user : null,
                        );
                      }}
                    />
                    {assetType.default_action === "transfer" ? (
                      <HandoverUserPicker
                        surface={surface}
                        taskId={taskId}
                        value={assetType.default_to_user}
                        disabled={readOnly || savingType}
                        aria-label={`${assetType.label} ${t("handover.allocator.receiver")}`}
                        onChange={(user) => {
                          if (!user) {
                            setLocalTypes((current) =>
                              current.map((row) =>
                                row.type === assetType.type
                                  ? { ...row, default_action: "transfer", default_to_user: null }
                                  : row,
                              ),
                            );
                            return;
                          }
                          void patchType(assetType, "transfer", user);
                        }}
                      />
                    ) : null}
                    {assetType.override_count > 0 ? (
                      <span className="text-caption text-ink-soft">
                        {t("handover.allocator.overrideCount", { count: assetType.override_count })}
                      </span>
                    ) : null}
                  </>
                )}
                {!isEmpty && assetType.detail_supported ? (
                  <Button
                    size="sm"
                    type="button"
                    variant="ghost"
                    disabled={readOnly}
                    onClick={() => setExpandedType(isExpanded ? null : assetType.type)}
                  >
                    {isExpanded ? t("handover.allocator.collapse") : t("handover.allocator.expand")}
                  </Button>
                ) : null}
              </div>
              {isExpanded && !isEmpty ? (
                <AssetTypeDetails
                  surface={surface}
                  taskId={taskId}
                  appKey={action.app_key}
                  assetType={assetType}
                  readOnly={readOnly}
                  onBusyChange={setDetailsBusy}
                  onSnapshotStale={onSnapshotStale}
                  onSaved={(result) => {
                    setLocalTypes((current) =>
                      current.map((row) =>
                        row.type === assetType.type
                          ? { ...row, override_count: result.override_count }
                          : row,
                      ),
                    );
                    onActionUpdated?.({
                      confirm_version: result.confirm_version,
                      overrides_version: result.overrides_version,
                    });
                  }}
                />
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function AssetActionSelect({
  value,
  releasable,
  disabled,
  onChange,
  "aria-label": ariaLabel,
}: {
  value: HandoverAssetAction;
  releasable: boolean;
  disabled?: boolean;
  onChange: (value: HandoverAssetAction) => void;
  "aria-label"?: string;
}) {
  const { t } = useI18n();
  return (
    <SelectInput
      className="w-40"
      value={value}
      disabled={disabled}
      aria-label={ariaLabel}
      title={!releasable ? t("handover.allocator.releaseDisabled") : undefined}
      onChange={(event) => onChange(event.currentTarget.value as HandoverAssetAction)}
    >
      <option value="transfer">{t("handover.allocator.action.transfer")}</option>
      <option value="release" disabled={!releasable}>
        {t("handover.allocator.action.release")}
      </option>
      <option value="skip">{t("handover.allocator.action.skip")}</option>
    </SelectInput>
  );
}

function AssetTypeDetails({
  surface,
  taskId,
  appKey,
  assetType,
  readOnly,
  onSaved,
  onBusyChange,
  onSnapshotStale,
}: {
  surface: HandoverSurface;
  taskId: number | string;
  appKey: string;
  assetType: HandoverAssetType;
  readOnly: boolean;
  onSaved: (result: { override_count: number; confirm_version: number; overrides_version: number }) => void;
  onBusyChange?: (busy: boolean) => void;
  onSnapshotStale?: () => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [drafts, setDrafts] = useState<Record<string, DraftOverride>>({});
  const [loadedOverrides, setLoadedOverrides] = useState(false);
  const [overridesVersion, setOverridesVersion] = useState(0);
  const [fullOverrides, setFullOverrides] = useState<DraftOverride[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const basePath = handoverAssetTypePath(surface, taskId, appKey, assetType.type);

  const overridesQuery = useQuery({
    queryKey: ["handover", "overrides", surface, String(taskId), appKey, assetType.type],
    queryFn: async () => apiRequest<HandoverOverridesPayload>(`${basePath}/overrides`),
  });

  useEffect(() => {
    if (!overridesQuery.data) {
      return;
    }
    const mapped = overridesQuery.data.overrides.map((entry) => ({
      asset_id: entry.asset_id,
      action: entry.action,
      to_user: entry.to_user ?? (entry.to_user_id ? { user_id: entry.to_user_id, name: entry.to_user_id } : null),
      label: entry.label,
    }));
    setFullOverrides(mapped);
    setOverridesVersion(overridesQuery.data.overrides_version);
    setLoadedOverrides(true);
    setDrafts(Object.fromEntries(mapped.map((entry) => [entry.asset_id, entry])));
    setError(null);
  }, [overridesQuery.data]);

  useEffect(() => {
    if (!overridesQuery.error) {
      return;
    }
    // overrides GET 失败不得永久挂在 loading；表面化错误
    setLoadedOverrides(false);
    const reason = apiErrorReason(overridesQuery.error);
    if (reason === "snapshot_stale") {
      setError(t("handover.portal.detail.snapshotStale"));
      setDrafts({});
      setFullOverrides([]);
      onSnapshotStale?.();
      return;
    }
    setError((overridesQuery.error as Error).message);
  }, [overridesQuery.error, onSnapshotStale, t]);

  const itemsQuery = useQuery({
    queryKey: ["handover", "items", surface, String(taskId), appKey, assetType.type, page, debouncedSearch],
    queryFn: () =>
      apiRequest<HandoverAssetItemsPage>(
        `${basePath}/items?page=${page}&page_size=50&q=${encodeURIComponent(debouncedSearch)}`,
      ),
    enabled: loadedOverrides,
  });

  useEffect(() => {
    if (!itemsQuery.error) {
      return;
    }
    const reason = apiErrorReason(itemsQuery.error);
    if (reason === "snapshot_stale") {
      setError(t("handover.portal.detail.snapshotStale"));
      setDrafts({});
      setFullOverrides([]);
      setLoadedOverrides(false);
      onSnapshotStale?.();
      return;
    }
    if (reason === "downstream_locked") {
      setError(t("handover.portal.detail.downstreamLocked"));
      return;
    }
    setError((itemsQuery.error as Error).message);
  }, [itemsQuery.error, onSnapshotStale, t]);

  const items = itemsQuery.data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((itemsQuery.data?.total ?? 0) / 50));

  const effectiveForItem = (item: HandoverAssetItem): DraftOverride => {
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
  };

  const isOverridden = (item: HandoverAssetItem): boolean => {
    const current = effectiveForItem(item);
    const sameAction = current.action === assetType.default_action;
    const sameUser =
      (current.to_user?.user_id ?? "") === (assetType.default_to_user?.user_id ?? "");
    return !(sameAction && (current.action !== "transfer" || sameUser));
  };

  const updateItem = (item: HandoverAssetItem, next: Partial<DraftOverride>) => {
    const base = effectiveForItem(item);
    const merged: DraftOverride = {
      ...base,
      ...next,
      asset_id: item.id,
      label: item.label,
    };
    // 条目级 transfer 也须先选接收人；无接收人时留在 draft 但不算合法 override 提交
    const sameAction = merged.action === assetType.default_action;
    const sameUser =
      (merged.to_user?.user_id ?? "") === (assetType.default_to_user?.user_id ?? "");
    setDrafts((current) => {
      const nextMap = { ...current };
      if (sameAction && (merged.action !== "transfer" || sameUser)) {
        delete nextMap[item.id];
      } else {
        nextMap[item.id] = merged;
      }
      return nextMap;
    });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      // PUT 整体替换：合并未出现在当前页的既有 override + 本页 drafts
      const pageIds = new Set(items.map((item) => item.id));
      const fromOtherPages = fullOverrides.filter((entry) => !pageIds.has(entry.asset_id));
      const byId = new Map<string, DraftOverride>();
      for (const entry of fromOtherPages) {
        byId.set(entry.asset_id, entry);
      }
      for (const entry of Object.values(drafts)) {
        byId.set(entry.asset_id, entry);
      }
      // Remove any that match defaults；transfer 无接收人的条目不得提交
      const overrides = [...byId.values()]
        .filter((entry) => isStillOverride(entry, assetType))
        .filter((entry) => entry.action !== "transfer" || Boolean(entry.to_user?.user_id))
        .map((entry) => ({
          asset_id: entry.asset_id,
          action: entry.action,
          to_user_id: entry.action === "transfer" ? (entry.to_user?.user_id ?? null) : null,
          label: entry.label,
        }));
      return apiRequest<{
        overrides_version: number;
        confirm_version: number;
        override_count: number;
        dropped_invalid: number;
      }>(`${basePath}/overrides`, {
        method: "PUT",
        body: { overrides_version: overridesVersion, overrides },
      });
    },
    onSuccess: (payload) => {
      setError(null);
      setOverridesVersion(payload.overrides_version);
      setFullOverrides(Object.values(drafts).filter((entry) => isStillOverride(entry, assetType)));
      onSaved({
        override_count: payload.override_count,
        confirm_version: payload.confirm_version,
        overrides_version: payload.overrides_version,
      });
      void queryClient.invalidateQueries({
        queryKey: ["handover", "overrides", surface, String(taskId), appKey, assetType.type],
      });
    },
    onError: async (err: Error) => {
      const reason = apiErrorReason(err);
      if (reason === "overrides_version_stale") {
        setError(t("handover.allocator.overridesStale"));
        await overridesQuery.refetch();
        return;
      }
      if (reason === "snapshot_stale") {
        setError(t("handover.portal.detail.snapshotStale"));
        setDrafts({});
        setFullOverrides([]);
        setLoadedOverrides(false);
        onSnapshotStale?.();
        return;
      }
      setError(err.message);
    },
  });

  useEffect(() => {
    onBusyChange?.(saveMutation.isPending);
  }, [onBusyChange, saveMutation.isPending]);

  const canSubmit = loadedOverrides && !readOnly && !saveMutation.isPending;
  const overridesLoading = overridesQuery.isLoading && !overridesQuery.isError;
  const itemsLoading = loadedOverrides && itemsQuery.isLoading && !itemsQuery.isError;
  const hasQueryError = Boolean(error);

  return (
    <div className="mt-3 space-y-3 border-t border-ink/10 pt-3">
      {itemsQuery.data?.stale && !debouncedSearch ? (
        <StatusBanner live="status" tone="amber" title={t("handover.allocator.stale")} />
      ) : null}
      {error ? <StatusBanner live="alert" tone="signal" title={error} /> : null}
      {overridesLoading ? (
        <p className="text-body text-ink-faint">{t("common.loading")}</p>
      ) : overridesQuery.isError && !loadedOverrides ? (
        // 已 surface 错误；不渲染空列表也不挂 loading
        null
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <TextInput
              className="max-w-xs"
              value={search}
              placeholder={t("handover.allocator.search")}
              aria-label={t("handover.allocator.search")}
              onChange={(event) => {
                setSearch(event.currentTarget.value);
                setPage(1);
              }}
            />
            <span className="text-caption text-ink-faint">
              {t("handover.allocator.totalItems", { total: itemsQuery.data?.total ?? 0 })}
            </span>
          </div>
          {itemsLoading ? (
            <p className="text-body text-ink-faint">{t("common.loading")}</p>
          ) : itemsQuery.isError && hasQueryError ? (
            null
          ) : (
            <ul className="grid gap-2">
              {items.map((item) => {
                const current = effectiveForItem(item);
                const overridden = isOverridden(item);
                return (
                  <li
                    key={item.id}
                    className={cn(
                      "flex flex-wrap items-start justify-between gap-2 rounded-[2px] border px-2.5 py-2",
                      overridden ? "border-ink/20 bg-paper" : "border-ink/8 bg-paper-deep/40 text-ink-soft",
                    )}
                    data-testid={`asset-item-${item.id}`}
                  >
                    <div className="min-w-0">
                      <p className="text-body font-medium text-ink">{item.label}</p>
                      {item.hint ? <p className="text-caption text-ink-faint">{item.hint}</p> : null}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <AssetActionSelect
                        value={current.action}
                        releasable={assetType.releasable}
                        disabled={readOnly}
                        aria-label={`${item.label} action`}
                        onChange={(next) =>
                          updateItem(item, {
                            action: next,
                            to_user: next === "transfer" ? current.to_user : null,
                          })
                        }
                      />
                      {current.action === "transfer" ? (
                        <HandoverUserPicker
                          surface={surface}
                          taskId={taskId}
                          value={current.to_user}
                          disabled={readOnly}
                          aria-label={`${item.label} ${t("handover.allocator.receiver")}`}
                          onChange={(user) => updateItem(item, { to_user: user, action: "transfer" })}
                        />
                      ) : null}
                      {overridden ? (
                        <span className="size-2 rounded-full bg-accent" aria-hidden="true" data-testid="override-dot" />
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Button size="sm" type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                ←
              </Button>
              <span className="text-caption text-ink-faint">
                {page} / {totalPages}
              </span>
              <Button size="sm" type="button" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                →
              </Button>
            </div>
            <Button
              size="sm"
              type="button"
              variant="primary"
              disabled={!canSubmit}
              loading={saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {t("handover.allocator.saveOverrides")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

function isStillOverride(entry: DraftOverride, assetType: HandoverAssetType): boolean {
  if (entry.action !== assetType.default_action) {
    return true;
  }
  if (entry.action === "transfer") {
    return (entry.to_user?.user_id ?? "") !== (assetType.default_to_user?.user_id ?? "");
  }
  return false;
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

import { Button } from "../../components/Button";
import { TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import type { HandoverAssetItem, HandoverAssetType } from "../../lib/domain";
import type { ActionSnapshotScope } from "./actionSnapshotCache";
import { AssetActionSelect } from "./AssetActionSelect";
import type { DraftOverride } from "./assetAllocatorModel";
import { HandoverUserPicker } from "./HandoverUserPicker";
import { useAssetTypeOverrides } from "./useAssetTypeOverrides";

export interface AssetTypeDetailsProps {
  scope: ActionSnapshotScope;
  assetType: HandoverAssetType;
  readOnly: boolean;
  snapshotEpoch: number;
  onSaved: (result: { override_count: number; confirm_version: number; overrides_version: number }) => void;
  onBusyChange?: (busy: boolean) => void;
  onSnapshotStale?: () => void;
}

export function AssetTypeDetails({
  scope,
  assetType,
  readOnly,
  snapshotEpoch,
  onSaved,
  onBusyChange,
  onSnapshotStale,
}: AssetTypeDetailsProps) {
  const { t } = useI18n();
  const overrides = useAssetTypeOverrides({
    scope,
    assetType,
    readOnly,
    snapshotEpoch,
    onSaved,
    onBusyChange,
    onSnapshotStale,
  });

  return (
    <div className="mt-3 space-y-3 border-t border-ink/10 pt-3">
      {overrides.showStaleBanner ? (
        <StatusBanner live="status" tone="amber" title={t("handover.allocator.stale")} />
      ) : null}
      {overrides.error ? <StatusBanner live="alert" tone="signal" title={overrides.error} /> : null}
      {overrides.incompleteTransferDraft ? (
        <StatusBanner live="alert" tone="signal" title={t("handover.allocator.receiverRequired")} />
      ) : null}
      {overrides.overridesLoading ? (
        <p className="text-body text-ink-faint">{t("common.loading")}</p>
      ) : overrides.overridesFailedBeforeLoad ? (
        // 已 surface 错误；不渲染空列表也不挂 loading
        null
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <TextInput
              className="max-w-xs"
              value={overrides.search}
              placeholder={t("handover.allocator.search")}
              aria-label={t("handover.allocator.search")}
              disabled={overrides.editorsLocked}
              onChange={(event) => overrides.onSearchChange(event.currentTarget.value)}
            />
            <span className="text-caption text-ink-faint">
              {t("handover.allocator.totalItems", { total: overrides.total })}
            </span>
          </div>
          {overrides.itemsLoading ? (
            <p className="text-body text-ink-faint">{t("common.loading")}</p>
          ) : overrides.itemsFailed ? (
            null
          ) : (
            <ul className="grid gap-2">
              {overrides.items.map((item) => (
                <AssetItemRow
                  key={item.id}
                  scope={scope}
                  item={item}
                  assetType={assetType}
                  current={overrides.effectiveForItem(item)}
                  overridden={overrides.isOverridden(item)}
                  disabled={overrides.editorsLocked}
                  onUpdate={(patch) => overrides.updateItem(item, patch)}
                />
              ))}
            </ul>
          )}
          <AssetTypeDetailsFooter
            page={overrides.page}
            totalPages={overrides.totalPages}
            disabled={overrides.editorsLocked}
            canSubmit={overrides.canSubmit}
            saving={overrides.saving}
            onPageChange={overrides.setPage}
            onSave={overrides.requestSave}
          />
        </>
      )}
    </div>
  );
}

/** 翻页与「保存例外」提交条。 */
function AssetTypeDetailsFooter({
  page,
  totalPages,
  disabled,
  canSubmit,
  saving,
  onPageChange,
  onSave,
}: {
  page: number;
  totalPages: number;
  disabled: boolean;
  canSubmit: boolean;
  saving: boolean;
  onPageChange: (updater: (current: number) => number) => void;
  onSave: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <Button size="sm" type="button" disabled={page <= 1 || disabled} onClick={() => onPageChange((p) => p - 1)}>
          ←
        </Button>
        <span className="text-caption text-ink-faint">
          {page} / {totalPages}
        </span>
        <Button
          size="sm"
          type="button"
          disabled={page >= totalPages || disabled}
          onClick={() => onPageChange((p) => p + 1)}
        >
          →
        </Button>
      </div>
      <Button size="sm" type="button" variant="primary" disabled={!canSubmit} loading={saving} onClick={onSave}>
        {t("handover.allocator.saveOverrides")}
      </Button>
    </div>
  );
}

function AssetItemRow({
  scope,
  item,
  assetType,
  current,
  overridden,
  disabled,
  onUpdate,
}: {
  scope: ActionSnapshotScope;
  item: HandoverAssetItem;
  assetType: HandoverAssetType;
  current: DraftOverride;
  overridden: boolean;
  disabled: boolean;
  onUpdate: (patch: Partial<DraftOverride>) => void;
}) {
  const { t } = useI18n();
  return (
    <li
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
          disabled={disabled}
          aria-label={`${item.label} action`}
          onChange={(next) => onUpdate({ action: next, to_user: next === "transfer" ? current.to_user : null })}
        />
        {current.action === "transfer" ? (
          <HandoverUserPicker
            surface={scope.surface}
            taskId={scope.taskId}
            value={current.to_user}
            disabled={disabled}
            aria-label={`${item.label} ${t("handover.allocator.receiver")}`}
            onChange={(user) => onUpdate({ to_user: user, action: "transfer" })}
          />
        ) : null}
        {overridden ? (
          <span className="size-2 rounded-full bg-accent" aria-hidden="true" data-testid="override-dot" />
        ) : null}
      </div>
    </li>
  );
}

import { Button } from "../../components/Button";
import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import type { HandoverAssetAction, HandoverAssetType, HandoverUserRef } from "../../lib/domain";
import type { ActionSnapshotScope } from "./actionSnapshotCache";
import { AssetActionSelect } from "./AssetActionSelect";
import { AssetTypeDetails } from "./AssetTypeDetails";
import { HandoverUserPicker } from "./HandoverUserPicker";

export interface AssetTypeRowProps {
  scope: ActionSnapshotScope;
  assetType: HandoverAssetType;
  readOnly: boolean;
  savingType: boolean;
  expanded: boolean;
  snapshotEpoch: number;
  onToggleExpanded: () => void;
  onPatch: (nextAction: HandoverAssetAction, nextUser: HandoverUserRef | null) => void;
  onDetailsBusyChange: (busy: boolean) => void;
  onSnapshotStale: () => void;
  onOverridesSaved: (result: { override_count: number; confirm_version: number; overrides_version: number }) => void;
}

export function AssetTypeRow({
  scope,
  assetType,
  readOnly,
  savingType,
  expanded,
  snapshotEpoch,
  onToggleExpanded,
  onPatch,
  onDetailsBusyChange,
  onSnapshotStale,
  onOverridesSaved,
}: AssetTypeRowProps) {
  const { t } = useI18n();
  const isEmpty = assetType.count === 0;
  return (
    <li
      className={cn("rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5", isEmpty && "opacity-60")}
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
          <AssetTypeControls
            scope={scope}
            assetType={assetType}
            disabled={readOnly || savingType}
            onPatch={onPatch}
          />
        )}
        {!isEmpty && assetType.detail_supported ? (
          <Button size="sm" type="button" variant="ghost" disabled={readOnly} onClick={onToggleExpanded}>
            {expanded ? t("handover.allocator.collapse") : t("handover.allocator.expand")}
          </Button>
        ) : null}
      </div>
      {expanded && !isEmpty ? (
        <AssetTypeDetails
          scope={scope}
          assetType={assetType}
          readOnly={readOnly}
          snapshotEpoch={snapshotEpoch}
          onBusyChange={onDetailsBusyChange}
          onSnapshotStale={onSnapshotStale}
          onSaved={onOverridesSaved}
        />
      ) : null}
    </li>
  );
}

/** 类型级默认动作 + 接收人 + 条目级例外计数。 */
function AssetTypeControls({
  scope,
  assetType,
  disabled,
  onPatch,
}: {
  scope: ActionSnapshotScope;
  assetType: HandoverAssetType;
  disabled: boolean;
  onPatch: (nextAction: HandoverAssetAction, nextUser: HandoverUserRef | null) => void;
}) {
  const { t } = useI18n();
  return (
    <>
      <AssetActionSelect
        value={assetType.default_action}
        releasable={assetType.releasable}
        disabled={disabled}
        aria-label={`${assetType.label} ${t("handover.allocator.defaultAction")}`}
        onChange={(next) => onPatch(next, next === "transfer" ? assetType.default_to_user : null)}
      />
      {assetType.default_action === "transfer" ? (
        <HandoverUserPicker
          surface={scope.surface}
          taskId={scope.taskId}
          value={assetType.default_to_user}
          disabled={disabled}
          aria-label={`${assetType.label} ${t("handover.allocator.receiver")}`}
          // 清空接收人 = 非法草稿；busy 锁住执行，直到选中新人并 PATCH
          onChange={(user) => onPatch("transfer", user)}
        />
      ) : null}
      {assetType.override_count > 0 ? (
        <span className="text-caption text-ink-soft">
          {t("handover.allocator.overrideCount", { count: assetType.override_count })}
        </span>
      ) : null}
    </>
  );
}

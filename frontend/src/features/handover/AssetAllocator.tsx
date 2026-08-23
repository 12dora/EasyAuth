import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import type { HandoverAction, HandoverAssetType } from "../../lib/domain";
import { AssetTypeRow } from "./AssetTypeRow";
import type { HandoverSurface } from "./surface";
import { useAssetAllocator } from "./useAssetAllocator";

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
  const scope = { surface, taskId, appKey: action.app_key };
  const allocator = useAssetAllocator({ scope, action, onActionUpdated, onBusyChange, onSnapshotStale });

  return (
    <div className="space-y-3" data-testid="asset-allocator">
      <p className="text-caption text-ink-soft" data-testid="asset-allocator-progress">
        {t("handover.allocator.arranged", {
          arranged: allocator.counts.arranged,
          total: allocator.counts.total,
        })}
      </p>
      {allocator.typeError ? <StatusBanner live="alert" tone="signal" title={allocator.typeError} /> : null}
      <ul className="grid gap-2">
        {allocator.types.map((assetType) => (
          <AssetTypeRow
            key={assetType.type}
            scope={scope}
            assetType={assetType}
            readOnly={readOnly}
            savingType={allocator.savingType}
            expanded={allocator.expandedType === assetType.type}
            snapshotEpoch={allocator.snapshotEpoch}
            onToggleExpanded={() => allocator.toggleExpanded(assetType.type)}
            onPatch={(nextAction, nextUser) => void allocator.patchType(assetType, nextAction, nextUser)}
            onDetailsBusyChange={allocator.setDetailsBusy}
            onSnapshotStale={allocator.handleSnapshotStale}
            onOverridesSaved={(result) => allocator.applyOverridesSaved(assetType, result)}
          />
        ))}
      </ul>
    </div>
  );
}

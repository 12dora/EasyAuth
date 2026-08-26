import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { AppTable, type ColumnsType } from "../../../components/antd/AppTable";
import { textColumn } from "../../../components/antd/columns";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { TextArea } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { PageState } from "../../../components/ui/PageState";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { HandoverCapabilityPayload } from "../../../lib/domain";

type HandoverAssetTypeRow = HandoverCapabilityPayload["handover_asset_types"][number];

export function HandoverCapabilityTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [declareOpen, setDeclareOpen] = useState(false);
  const [reason, setReason] = useState("");
  const queryKey = ["console", "handover-capability", appKey];

  const query = useQuery({
    queryKey,
    queryFn: () =>
      apiRequest<HandoverCapabilityPayload>(`/console/api/v1/lifecycle/apps/${appKey}/handover-capability`),
    enabled: Boolean(appKey),
  });

  const syncMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/lifecycle/apps/${appKey}/handover-capability/sync`, {
        method: "POST",
        body: {},
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey }),
  });

  const declareMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/lifecycle/apps/${appKey}/handover-capability`, {
        method: "POST",
        body: { reason: reason.trim() },
      }),
    onSuccess: () => {
      setDeclareOpen(false);
      setReason("");
      void queryClient.invalidateQueries({ queryKey });
    },
  });

  if (query.error && !query.data) {
    return (
      <PageState
        tone="signal"
        title={t("handover.console.capability.loadFailed")}
        description={(query.error as Error).message}
        action={
          <Button type="button" onClick={() => void query.refetch()}>
            {t("common.retry")}
          </Button>
        }
      />
    );
  }

  const data = query.data;
  const state = data?.handover_capability ?? "undeclared";

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-ink">{t("handover.console.capability.title")}</h2>
        <Badge tone={state === "declared" ? "evergreen" : state === "none" ? "faint" : "amber"}>
          {t(
            state === "declared"
              ? "handover.console.capability.state.declared"
              : state === "none"
                ? "handover.console.capability.state.none"
                : "handover.console.capability.state.undeclared",
          )}
        </Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button type="button" loading={syncMutation.isPending} onClick={() => syncMutation.mutate()}>
          {t("handover.console.capability.sync")}
        </Button>
        <Button type="button" variant="ghost-danger" onClick={() => setDeclareOpen(true)}>
          {t("handover.console.capability.declareNone")}
        </Button>
      </div>
      {state === "declared" && (data?.handover_asset_types?.length ?? 0) > 0 ? (
        <div className="space-y-2">
          <h3 className="text-body font-semibold text-ink">{t("handover.console.capability.assetTypes")}</h3>
          <HandoverAssetTypeTable rows={data!.handover_asset_types} />
        </div>
      ) : null}

      {declareOpen ? (
        <Dialog
          title={t("handover.console.capability.declareNone")}
          size="sm"
          onClose={() => setDeclareOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setDeclareOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={reason.trim().length < 10}
                loading={declareMutation.isPending}
                onClick={() => declareMutation.mutate()}
              >
                {t("handover.console.capability.declareNoneConfirm")}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <StatusBanner live="alert" tone="signal" title={t("handover.console.capability.declareNoneWarning")} />
            <TextArea
              value={reason}
              aria-label={t("handover.console.capability.declareNoneReason")}
              onChange={(event) => setReason(event.currentTarget.value)}
            />
          </div>
        </Dialog>
      ) : null}
    </PanelSurface>
  );
}

/** 资产类型由能力接口一次返回全量, 因此分页与筛选都在客户端完成。 */
function HandoverAssetTypeTable({ rows }: { rows: HandoverAssetTypeRow[] }) {
  const { t } = useI18n();
  const columns: ColumnsType<HandoverAssetTypeRow> = [
    textColumn<HandoverAssetTypeRow>({
      key: "type",
      title: t("handover.console.capability.col.type"),
      mono: true,
      filter: true,
      width: 220,
    }),
    textColumn<HandoverAssetTypeRow>({ key: "label", title: t("handover.console.capability.col.label") }),
    textColumn<HandoverAssetTypeRow>({
      key: "detail_supported",
      title: t("handover.console.capability.col.detail"),
      getValue: (row) => supportMark(row.detail_supported),
      width: 140,
    }),
    textColumn<HandoverAssetTypeRow>({
      key: "releasable",
      title: t("handover.console.capability.col.releasable"),
      getValue: (row) => supportMark(row.releasable),
      width: 140,
    }),
  ];

  // 固定列 220(类型) + 140(明细) + 140(可释放) = 500, 唯一的弹性列(名称)留 240 -> 740;
  // 比卡片窄, 桌面端由 antd 的 min-width:100% 拉满, 名称列吃掉剩余宽度。
  return <AppTable<HandoverAssetTypeRow> columns={columns} dataSource={rows} minWidth={740} rowKey="type" />;
}

function supportMark(supported: boolean): string {
  return supported ? "✓" : "—";
}

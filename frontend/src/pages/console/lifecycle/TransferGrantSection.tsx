import { Button } from "../../../components/Button";
import { Field, SelectInput } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverTaskDetail, TransferPlanItem } from "../../../lib/domain";
import { formatDateTime } from "../../../lib/status";
import { transferDiffEntries } from "./handoverTaskDetailModel";
import { TransferDiffGroup } from "./TransferDiffGroup";
import { useTransferGrantPlan } from "./useTransferGrantPlan";

export interface TransferGrantSectionProps {
  task: HandoverTaskDetail;
  taskId: string;
  onChanged: () => void;
  canOperate: boolean;
}

/** 转岗: 本人权限调整。选岗位模板 → 生成收回/新增/保留差异 → 勾选确认。 */
export function TransferGrantSection({ task, taskId, onChanged, canOperate }: TransferGrantSectionProps) {
  const { t } = useI18n();
  const grant = useTransferGrantPlan(task, taskId, onChanged);
  const plan = grant.plan;
  const confirmed = Boolean(plan?.confirmed_at);
  const readOnly = confirmed || !canOperate;

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("handover.transfer.grantTitle")}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("handover.transfer.grantHint")}</p>
      </div>
      {grant.templatesError ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("onboarding.templates.loadFailed")}
          message={(grant.templatesError as Error).message}
        />
      ) : null}
      <div className="flex flex-wrap items-end gap-2">
        <div className="w-64">
          <Field label={t("handover.transfer.template")}>
            <SelectInput
              value={grant.templateId}
              disabled={readOnly}
              onChange={(event) => grant.setTemplateId(event.currentTarget.value)}
            >
              <option value="">{t("handover.transfer.templatePlaceholder")}</option>
              {grant.templates.map((template) => (
                <option key={template.id} value={String(template.id)}>
                  {template.name}
                  {template.current_revision ? ` · r${template.current_revision}` : ""}
                </option>
              ))}
            </SelectInput>
          </Field>
        </div>
        <Button
          type="button"
          disabled={!grant.templateId || readOnly || grant.confirmMutation.isPending}
          loading={grant.buildMutation.isPending}
          onClick={() => grant.buildMutation.mutate()}
        >
          {t("handover.transfer.buildDiff")}
        </Button>
      </div>
      {plan ? (
        <TransferPlanPanel
          plan={plan}
          nameMap={grant.nameMap}
          readOnly={readOnly}
          confirmed={confirmed}
          revokeChecked={grant.revokeChecked}
          addChecked={grant.addChecked}
          onToggleRevoke={grant.toggleRevoke}
          onToggleAdd={grant.toggleAdd}
          buildPending={grant.buildMutation.isPending}
          confirmPending={grant.confirmMutation.isPending}
          onConfirm={() => grant.confirmMutation.mutate()}
        />
      ) : null}
    </PanelSurface>
  );
}

interface TransferPlanPanelProps {
  plan: TransferPlanItem;
  nameMap: Map<string, string>;
  readOnly: boolean;
  confirmed: boolean;
  revokeChecked: Record<string, boolean>;
  addChecked: Record<string, boolean>;
  onToggleRevoke: (key: string, value: boolean) => void;
  onToggleAdd: (key: string, value: boolean) => void;
  buildPending: boolean;
  confirmPending: boolean;
  onConfirm: () => void;
}

/** 差异面板: 收回/新增/保留三栏勾选 + 确认落库。 */
function TransferPlanPanel({
  plan,
  nameMap,
  readOnly,
  confirmed,
  revokeChecked,
  addChecked,
  onToggleRevoke,
  onToggleAdd,
  buildPending,
  confirmPending,
  onConfirm,
}: TransferPlanPanelProps) {
  const { t } = useI18n();
  const { revoke: revokeEntries, add: addEntries, keep: keepEntries } = transferDiffEntries(plan);
  return (
    <div className="space-y-4">
      <p className="text-body leading-5 text-ink">
        {t("handover.transfer.diffSummary", {
          revoke: revokeEntries.length,
          add: addEntries.length,
          keep: keepEntries.length,
        })}
      </p>
      <p className="text-caption text-ink-faint">
        {t("handover.transfer.boundRevision", {
          template: plan.template_name || "-",
          revision: plan.template_revision ?? "-",
        })}
      </p>
      {confirmed ? (
        <div>
          <StatusBanner
            live="status"
            tone="evergreen"
            title={t("handover.transfer.confirmedAt", { time: formatDateTime(plan.confirmed_at) })}
          />
        </div>
      ) : null}
      <div className="grid gap-4 lg:grid-cols-3">
        <TransferDiffGroup
          title={t("handover.transfer.revoke")}
          entries={revokeEntries}
          nameMap={nameMap}
          readOnly={readOnly}
          checked={revokeChecked}
          onToggle={onToggleRevoke}
        />
        <TransferDiffGroup
          title={t("handover.transfer.add")}
          entries={addEntries}
          nameMap={nameMap}
          readOnly={readOnly}
          checked={addChecked}
          onToggle={onToggleAdd}
        />
        <TransferDiffGroup
          title={t("handover.transfer.keep")}
          entries={keepEntries}
          nameMap={nameMap}
          readOnly
          checked={null}
        />
      </div>
      {!readOnly ? (
        <Button
          type="button"
          variant="primary"
          disabled={buildPending}
          loading={confirmPending}
          onClick={onConfirm}
        >
          {t("handover.transfer.confirm")}
        </Button>
      ) : null}
    </div>
  );
}

import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverAction, HandoverGrantItemRow } from "../../../lib/domain";
import { grantTypeLabel } from "../../../lib/status";
import { groupGrantItemsByApp } from "./handoverWizardModel";
import { StepSection } from "./HandoverWizardChrome";

export interface HandoverWizardGrantsStepProps {
  apps: HandoverAction[];
  items: HandoverGrantItemRow[];
  selection: Record<number, boolean>;
  isLoading: boolean;
  error: unknown;
  onToggle: (id: number, checked: boolean) => void;
}

export function HandoverWizardGrantsStep({
  apps,
  items,
  selection,
  isLoading,
  error,
  onToggle,
}: HandoverWizardGrantsStepProps) {
  const { t } = useI18n();
  return (
    <StepSection hint={t("handover.wizard.grants.hint")}>
      {error ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("handover.wizard.grants.loadFailed")}
          message={(error as Error).message}
        />
      ) : null}
      {isLoading ? <p className="text-body text-ink-faint">{t("common.loading")}</p> : null}
      {!isLoading && !error ? (
        <GrantItemsChecklist apps={apps} items={items} selection={selection} onToggle={onToggle} />
      ) : null}
    </StepSection>
  );
}

function GrantItemsChecklist({
  apps,
  items,
  selection,
  onToggle,
}: {
  apps: HandoverAction[];
  items: HandoverGrantItemRow[];
  selection: Record<number, boolean>;
  onToggle: (id: number, checked: boolean) => void;
}) {
  const { t } = useI18n();
  const grouped = groupGrantItemsByApp(apps, items);
  if (grouped.length === 0) {
    return <p className="text-body text-ink-soft">{t("handover.wizard.grants.empty")}</p>;
  }
  return (
    <div className="space-y-4">
      {grouped.map(({ action, items: appItems }) => (
        <div key={action.app_key} className="space-y-2">
          <h3 className="text-body font-semibold text-ink">{action.app_name || action.app_key}</h3>
          <ul className="grid gap-1.5">
            {appItems.map((item) => (
              <li key={item.id}>
                <label className="flex items-center gap-2.5 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2 text-body text-ink">
                  <input
                    type="checkbox"
                    disabled={item.status !== "pending"}
                    checked={selection[item.id] ?? item.selected}
                    onChange={(event) => onToggle(item.id, event.currentTarget.checked)}
                  />
                  <span className="flex-1 font-medium">{item.name || item.key}</span>
                  <span className="text-caption text-ink-faint">
                    {item.kind === "group" ? t("handover.diff.kind.group") : t("handover.diff.kind.permission")}
                    {" · "}
                    {grantTypeLabel(t, item.grant_type)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

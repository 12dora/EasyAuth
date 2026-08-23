import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppSummary } from "../../../../lib/domain";
import { overviewMetricValues } from "./overviewModel";

export function OverviewMetrics({ app, issueCount }: { app?: AppSummary; issueCount: number }) {
  const { t } = useI18n();
  const { authorizationGroupCount, permissionCount, credentialCount } = overviewMetricValues(app);

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric
        label={t("console.overview.metric.authorizationGroup")}
        value={authorizationGroupCount}
      />
      <Metric label={t("console.overview.metric.permission")} value={permissionCount} />
      <Metric label={t("console.overview.metric.credential")} value={credentialCount} />
      <Metric label={t("console.overview.issues")} value={issueCount} tone={issueCount > 0 ? "signal" : undefined} />
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: "signal" }) {
  return (
    <PanelSurface>
      <span className="text-xs font-semibold text-ink-faint">{label}</span>
      <strong className={`mt-2 block text-2xl font-semibold leading-none ${tone === "signal" ? "text-signal" : "text-ink"}`}>
        {value}
      </strong>
    </PanelSurface>
  );
}

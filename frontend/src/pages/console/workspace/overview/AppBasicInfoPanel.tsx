import type { ReactNode } from "react";

import { Badge } from "../../../../components/Badge";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppSummary } from "../../../../lib/domain";
import { formatDateTime, readinessLabel } from "../../../../lib/status";
import { safeJoin } from "../utils";

export function AppBasicInfoPanel({ app, status }: { app?: AppSummary; status: string | null | undefined }) {
  const { t } = useI18n();

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("console.overview.basicInfo")}</h2>
        <Badge tone={app?.is_active === false ? "neutral" : "evergreen"}>
          {app?.is_active === false ? t("common.disabled") : t("common.enabled")}
        </Badge>
      </div>
      <AppBasicInfoRows app={app} status={status} />
      {app?.description ? <p className="max-w-3xl text-body leading-5 text-ink-soft">{app.description}</p> : null}
    </PanelSurface>
  );
}

function AppBasicInfoRows({ app, status }: { app?: AppSummary; status: string | null | undefined }) {
  const { t } = useI18n();

  return (
    <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
      <BasicInfoItem label={t("console.overview.field.appName")} value={app?.name || "-"} />
      <BasicInfoItem label={t("console.overview.field.appKey")} value={<code>{app?.app_key || "-"}</code>} />
      <BasicInfoItem label={t("appList.column.owners")} value={safeJoin(app?.owners)} />
      <BasicInfoItem label={t("console.overview.field.developers")} value={safeJoin(app?.developers)} />
      <BasicInfoItem label={t("common.updatedAt")} value={formatDateTime(app?.updated_at)} />
      <BasicInfoItem label={t("console.overview.field.configStatus")} value={`${readinessLabel(t, status)}`} />
    </dl>
  );
}

function BasicInfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/8 pb-2">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="m-0 min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../components/Badge";
import { ButtonLink } from "../../components/ButtonLink";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { ConsoleAuthentikSection } from "./ConsoleAuthentikSection";
import { ConsoleDingtalkNotifySection } from "./ConsoleDingtalkNotifySection";
import { ConsoleDingtalkSection } from "./ConsoleDingtalkSection";
import {
  SETTINGS_QUERY_KEY,
  SETTINGS_URL,
  summaryPills,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";
import { TwoFactorSection } from "./TwoFactorSection";

export function ConsoleSettingsPage() {
  const { t } = useI18n();
  const settingsQuery = useQuery({
    queryKey: SETTINGS_QUERY_KEY,
    queryFn: () => apiRequest<IntegrationSettingsPayload>(SETTINGS_URL),
  });
  const settings = settingsQuery.data;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("settingsPlaceholder.eyebrow")}
        title={t("settingsPlaceholder.console.title")}
        description={t("settings.integration.description")}
        actions={<ButtonLink to="/console/operations/dependency-health">{t("settings.integration.healthLink")}</ButtonLink>}
      />
      {settingsQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("settings.integration.loadFailed")} message={(settingsQuery.error as Error).message} />
      ) : null}
      {settings ? <SummaryStrip settings={settings} /> : null}
      <div className="grid items-stretch gap-6 md:grid-cols-2 xl:grid-cols-3">
        <ConsoleAuthentikSection settings={settings} />
        <ConsoleDingtalkSection settings={settings} />
        <ConsoleDingtalkNotifySection settings={settings} />
        <TwoFactorSection />
      </div>
    </div>
  );
}

/** 概览条: 三个指标全部由既有载荷字段推导, 载荷没到之前整条不渲染。 */
function SummaryStrip({ settings }: { settings: IntegrationSettingsPayload }) {
  const { t } = useI18n();
  return (
    <dl className="grid gap-3 sm:grid-cols-3">
      {summaryPills(t, settings).map((pill) => (
        <div
          key={pill.key}
          className="flex items-center justify-between gap-3 border border-ink/12 bg-paper-soft px-3 py-2.5"
        >
          <dt className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">{pill.label}</dt>
          <dd>
            <Badge tone={pill.tone}>{pill.value}</Badge>
          </dd>
        </div>
      ))}
    </dl>
  );
}

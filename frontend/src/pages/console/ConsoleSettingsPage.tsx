import { useQuery } from "@tanstack/react-query";

import { ButtonLink } from "../../components/ButtonLink";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { ConsoleAuthentikSection } from "./ConsoleAuthentikSection";
import { ConsoleDingtalkSection } from "./ConsoleDingtalkSection";
import { SETTINGS_QUERY_KEY, SETTINGS_URL, type IntegrationSettingsPayload } from "./consoleSettingsModel";
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
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <ConsoleAuthentikSection settings={settings} />
        <ConsoleDingtalkSection settings={settings} />
      </div>
      <TwoFactorSection />
    </div>
  );
}

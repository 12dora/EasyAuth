import { Compass } from "lucide-react";

import { ButtonLink } from "../../../components/ButtonLink";
import { CodeBlock } from "../../../components/CodeBlock";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import { buildIntegrationSnippets, integrationHintKey } from "./integrationSnippets";
import { StepFooter, StepPanel } from "./StepLayout";
import type { CreatedCredentialKind } from "./types";
import { useConfigurationStatusQuery } from "./useConfigurationStatusQuery";

export function DoneStep({
  appKey,
  appName,
  credentialKind,
}: {
  appKey: string;
  appName: string;
  credentialKind: CreatedCredentialKind | null;
}) {
  const { t } = useI18n();
  const statusQuery = useConfigurationStatusQuery(appKey);
  const issues = statusQuery.data?.data ?? [];
  const { integrationSnippet, curlSnippet } = buildIntegrationSnippets({
    appKey,
    appName,
    origin: window.location.origin,
    credentialKind,
  });

  if (!appKey) {
    return (
      <StepPanel title={t("wizard.done.title")} description={t("wizard.error.appMissing")}>
        <StepFooter>
          <ButtonLink variant="primary" to="/console/apps/new">
            {t("wizard.error.restart")}
          </ButtonLink>
        </StepFooter>
      </StepPanel>
    );
  }

  return (
    <StepPanel title={t("wizard.done.title")} description={t("wizard.done.description")}>
      {statusQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("wizard.authz.statusLoadFailed")} message={(statusQuery.error as Error).message} />
      ) : null}
      {statusQuery.data ? (
        issues.length === 0 ? (
          <StatusBanner live="status" tone="evergreen" title={t("wizard.done.configReady")} />
        ) : (
          <StatusBanner live="status" tone="amber" title={t("wizard.done.configIssues", { count: issues.length })} />
        )
      ) : null}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-ink">{t("wizard.done.integrationTitle")}</h3>
        <CodeBlock language="env" code={integrationSnippet} />
        <CodeBlock language="curl" code={curlSnippet} />
        <p className="text-body text-ink-soft">{t(integrationHintKey(credentialKind))}</p>
      </div>
      <StepFooter>
        <ButtonLink to={`/console/apps/${appKey}?tab=guide`}>{t("wizard.done.guideLink")}</ButtonLink>
        <ButtonLink variant="primary" icon={<Compass size={16} />} to={`/console/apps/${appKey}`}>
          {t("wizard.openWorkspace")}
        </ButtonLink>
      </StepFooter>
    </StepPanel>
  );
}

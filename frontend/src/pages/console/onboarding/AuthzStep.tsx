import { RefreshCcw } from "lucide-react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import type { ConfigurationIssue } from "../../../lib/domain";
import { StepFooter, StepPanel } from "./StepLayout";
import { useConfigurationStatusQuery } from "./useConfigurationStatusQuery";
import { isBlockingIssue } from "./wizardParsing";

export function AuthzStep({ appKey, onBack, onContinue }: { appKey: string; onBack: () => void; onContinue: () => void }) {
  const { t } = useI18n();
  const statusQuery = useConfigurationStatusQuery(appKey);
  const issues = statusQuery.data?.data ?? [];
  const blockingCount = issues.filter(isBlockingIssue).length;

  return (
    <StepPanel title={t("wizard.authz.title")} description={t("wizard.authz.description")}>
      {statusQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("wizard.authz.statusLoadFailed")} message={(statusQuery.error as Error).message} />
      ) : null}
      {statusQuery.data ? (
        issues.length === 0 ? (
          <StatusBanner live="status" tone="evergreen" title={t("wizard.authz.ready")} />
        ) : (
          <StatusBanner
            live={blockingCount > 0 ? "alert" : "status"}
            tone={blockingCount > 0 ? "signal" : "amber"}
            title={t("wizard.authz.issuesFound", { count: issues.length })}
          />
        )
      ) : null}
      {issues.length > 0 ? <ConfigurationIssueTable issues={issues} /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <ButtonLink to={`/console/apps/${appKey}?tab=matrix`}>{t("wizard.authz.goMatrix")}</ButtonLink>
        <ButtonLink to={`/console/apps/${appKey}?tab=rules`}>{t("wizard.authz.goRules")}</ButtonLink>
        <ButtonLink to={`/console/apps/${appKey}?tab=catalog`}>{t("wizard.authz.goCatalog")}</ButtonLink>
        <Button icon={<RefreshCcw size={16} />} loading={statusQuery.isFetching} onClick={() => void statusQuery.refetch()}>
          {t("wizard.authz.recheck")}
        </Button>
      </div>
      <StepFooter>
        <Button onClick={onBack}>{t("common.back")}</Button>
        <Button variant="primary" onClick={onContinue}>
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}

function ConfigurationIssueTable({ issues }: { issues: ConfigurationIssue[] }) {
  const { t } = useI18n();

  return (
    <div className="overflow-x-auto rounded-[3px] border border-ink/10">
      <table className="w-full text-body">
        <thead className="bg-paper-soft text-left text-label uppercase tracking-caps-wide text-ink-soft">
          <tr>
            <th className="px-3 py-2">{t("wizard.authz.issue.column.severity")}</th>
            <th className="px-3 py-2">{t("wizard.authz.issue.column.message")}</th>
            <th className="px-3 py-2">{t("wizard.authz.issue.column.subject")}</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr key={`${issue.code ?? "issue"}:${issue.subject ?? index}`} className="border-t border-ink/8">
              <td className="px-3 py-2">
                <Badge tone={isBlockingIssue(issue) ? "signal" : "amber"}>
                  {isBlockingIssue(issue) ? t("wizard.authz.severity.blocking") : t("wizard.authz.severity.warning")}
                </Badge>
              </td>
              <td className="px-3 py-2 text-ink">{issue.message ?? issue.code ?? "-"}</td>
              <td className="px-3 py-2">
                <code className="text-xs">{issue.subject || "-"}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

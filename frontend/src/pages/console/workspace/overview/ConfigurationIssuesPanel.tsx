import { AppTable } from "../../../../components/antd/AppTable";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { ConfigurationIssue } from "../../../../lib/domain";
import { configurationIssueColumns } from "./overviewColumns";

/** 配置问题没有服务端主键, 用「代码 + 对象 + 说明」拼出稳定行身份。 */
function issueRowKey(issue: ConfigurationIssue): string {
  return [issue.code ?? "", issue.subject ?? issue.target_id ?? "", issue.message ?? ""].join("|");
}

export function ConfigurationIssuesPanel({ issues, isLoading }: { issues: ConfigurationIssue[]; isLoading: boolean }) {
  const { t } = useI18n();

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("console.overview.issues")}</h2>
      </div>
      <AppTable<ConfigurationIssue>
        columns={configurationIssueColumns(t)}
        dataSource={issues}
        rowKey={issueRowKey}
        loading={isLoading}
        empty={<EmptyState title={t("console.overview.issuesEmpty")} description={t("console.overview.issuesEmptyDescription")} />}
      />
    </PanelSurface>
  );
}

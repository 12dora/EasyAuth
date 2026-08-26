import { RefreshCcw } from "lucide-react";

import { AppTable, type ColumnsType } from "../../../components/antd/AppTable";
import { statusColumn, textColumn } from "../../../components/antd/columns";
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
  const columns: ColumnsType<ConfigurationIssue> = [
    statusColumn<ConfigurationIssue>({
      key: "severity",
      title: t("wizard.authz.issue.column.severity"),
      getValue: (issue) => (isBlockingIssue(issue) ? "blocking" : "warning"),
      options: [
        { value: "blocking", label: t("wizard.authz.severity.blocking"), tone: "signal" },
        { value: "warning", label: t("wizard.authz.severity.warning"), tone: "amber" },
      ],
      width: 140,
    }),
    textColumn<ConfigurationIssue>({
      key: "message",
      title: t("wizard.authz.issue.column.message"),
      getValue: (issue) => issue.message ?? issue.code ?? "",
      // 问题说明是整表最长的一列: 不省略, 让长文案换行展示完整。
      ellipsis: false,
      filter: true,
    }),
    textColumn<ConfigurationIssue>({
      key: "subject",
      title: t("wizard.authz.issue.column.subject"),
      mono: true,
      width: 260,
    }),
  ];

  // 配置检查结果由 configuration-status 一次返回全量, 分页与筛选都在客户端完成。
  return (
    <AppTable<ConfigurationIssue>
      columns={columns}
      dataSource={issues}
      rowKey={(issue) => `${issue.code ?? "issue"}:${issue.subject ?? ""}:${issue.message ?? ""}`}
    />
  );
}

import { useMemo } from "react";

import { CodeBlock } from "../../../../components/CodeBlock";
import { StatusBanner } from "../../../../components/StatusBanner";
import { AppTable } from "../../../../components/antd/AppTable";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { queryTestGrantColumns, queryTestGroupColumns } from "./queryTestColumns";
import type { QueryTestGrant, QueryTestGroup, StructuredQueryTestResult } from "./queryTestModel";

export function QueryTestResultView({ result }: { result: StructuredQueryTestResult }) {
  const { t } = useI18n();
  const groups = result.groups ?? [];
  const grants = result.grants ?? [];
  // 联调结果一次性返回全量, 因此两张表都是纯客户端表: 分页/筛选/排序都由 antd 完成。
  const groupColumns = useMemo(
    () => queryTestGroupColumns(t, result.snapshot_version),
    [result.snapshot_version, t],
  );
  const grantColumns = useMemo(
    () => queryTestGrantColumns(t, result.snapshot_version),
    [result.snapshot_version, t],
  );

  return (
    <>
      <StatusBanner
        live="status"
        tone={result.allowed ? "evergreen" : "neutral"}
        title={result.allowed ? t("wizard.verify.hit") : t("wizard.verify.noHit")}
      />
      <QueryTestSummaryTiles result={result} />
      <AppTable<QueryTestGroup>
        columns={groupColumns}
        dataSource={groups}
        emptyTitle={t("console.queryTest.groupsEmpty")}
        rowKey={(group) => group.key ?? group.name ?? ""}
      />
      <AppTable<QueryTestGrant>
        columns={grantColumns}
        dataSource={grants}
        emptyTitle={t("console.queryTest.grantsEmpty")}
        minWidth={1400}
        rowKey={(grant) => `${grant.permission ?? ""}:${grant.scope ?? ""}:${grant.source_key ?? ""}`}
      />
      <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
    </>
  );
}

function QueryTestSummaryTiles({ result }: { result: StructuredQueryTestResult }) {
  const { t } = useI18n();

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <PanelSurface>
        <span className="text-xs font-semibold text-ink-faint">{t("common.source")}</span>
        <strong className="mt-2 block text-sm font-semibold text-ink">{result.source ?? "-"}</strong>
      </PanelSurface>
      <PanelSurface>
        <span className="text-xs font-semibold text-ink-faint">{t("wizard.verify.snapshotVersion")}</span>
        <strong className="mt-2 block text-sm font-semibold text-ink">{result.snapshot_version ?? "-"}</strong>
      </PanelSurface>
    </div>
  );
}

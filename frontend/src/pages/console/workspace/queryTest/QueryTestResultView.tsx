import { getCoreRowModel, getPaginationRowModel, useReactTable } from "@tanstack/react-table";

import { CodeBlock } from "../../../../components/CodeBlock";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { WorkspaceTable } from "../table/WorkspaceTable";
import { queryTestGrantColumns, queryTestGroupColumns } from "./queryTestColumns";
import type { StructuredQueryTestResult } from "./queryTestModel";

export function QueryTestResultView({ result }: { result: StructuredQueryTestResult }) {
  const { t } = useI18n();
  const groups = result.groups ?? [];
  const grants = result.grants ?? [];
  const groupTable = useReactTable({
    data: groups,
    columns: queryTestGroupColumns(t, result.snapshot_version),
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const grantTable = useReactTable({
    data: grants,
    columns: queryTestGrantColumns(t, result.snapshot_version),
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <>
      <StatusBanner
        live="status"
        tone={result.allowed ? "evergreen" : "neutral"}
        title={result.allowed ? t("wizard.verify.hit") : t("wizard.verify.noHit")}
      />
      <QueryTestSummaryTiles result={result} />
      <WorkspaceTable table={groupTable} totalItems={groups.length} empty={t("console.queryTest.groupsEmpty")} />
      <WorkspaceTable table={grantTable} totalItems={grants.length} empty={t("console.queryTest.grantsEmpty")} />
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

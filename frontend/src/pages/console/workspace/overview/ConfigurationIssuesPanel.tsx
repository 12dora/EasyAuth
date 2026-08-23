import { getCoreRowModel, getPaginationRowModel, useReactTable } from "@tanstack/react-table";

import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { ConfigurationIssue } from "../../../../lib/domain";
import { TableView } from "../../../../components/ui/TableView";
import { configurationIssueColumns } from "./overviewColumns";

export function ConfigurationIssuesPanel({ issues, isLoading }: { issues: ConfigurationIssue[]; isLoading: boolean }) {
  const { t } = useI18n();
  const table = useReactTable({
    data: issues,
    columns: configurationIssueColumns(t),
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("console.overview.issues")}</h2>
      </div>
      <TableView
        table={table}
        totalItems={issues.length}
        isLoading={isLoading}
        empty={<EmptyState title={t("console.overview.issuesEmpty")} description={t("console.overview.issuesEmptyDescription")} />}
      />
    </PanelSurface>
  );
}

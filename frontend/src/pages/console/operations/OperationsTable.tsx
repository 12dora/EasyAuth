import type { Table } from "@tanstack/react-table";

import { EmptyState } from "../../../components/ui/EmptyState";
import { TableView } from "../../../components/ui/TableView";
import { useI18n } from "../../../i18n/I18nProvider";
import type { OperationRow } from "./operationRow";

export function OperationsTable({
  table,
  isLoading,
  totalItems,
}: {
  table: Table<OperationRow>;
  isLoading: boolean;
  totalItems: number;
}) {
  const { t } = useI18n();
  return (
    <TableView
      table={table}
      isLoading={isLoading}
      totalItems={totalItems}
      empty={<EmptyState title={t("console.operations.empty")} description={t("console.operations.emptyDescription")} />}
    />
  );
}

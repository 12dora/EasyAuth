import { AppTable } from "../../../components/antd/AppTable";
import { useI18n } from "../../../i18n/I18nProvider";
import type { OperationRow } from "./operationRow";
import type { OperationsSectionController } from "./useOperationsSection";

export function OperationsTable({ controller }: { controller: OperationsSectionController }) {
  const { t } = useI18n();

  return (
    <AppTable<OperationRow>
      columns={controller.columns}
      dataSource={controller.rows}
      emptyTitle={t("console.operations.empty")}
      emptyDescription={t("console.operations.emptyDescription")}
      loading={controller.query.isLoading}
      minWidth={controller.minWidth}
      rowKey={controller.rowKey}
      {...controller.tableProps}
    />
  );
}

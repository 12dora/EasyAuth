import { AppTable, type AppTableProps, type ColumnsType } from "../../../components/antd/AppTable";
import { useI18n } from "../../../i18n/I18nProvider";

/**
 * 运营分区的表格。
 *
 * 行类型是泛型: 授权明细的行由契约解析器产出(`AccessGrantRow`), 其余分区共用松散的
 * 运营行, 两者的列定义不能互相赋值, 因此由调用方在判别分区后各自实例化。
 */
export function OperationsTable<T extends object>({
  columns,
  isLoading,
  minWidth,
  rowKey,
  rows,
  tableProps,
}: {
  columns: ColumnsType<T>;
  isLoading: boolean;
  minWidth?: number;
  rowKey: (row: T) => string;
  rows: T[];
  tableProps: Pick<AppTableProps<T>, "pagination" | "onChange">;
}) {
  const { t } = useI18n();

  return (
    <AppTable<T>
      columns={columns}
      dataSource={rows}
      emptyTitle={t("console.operations.empty")}
      emptyDescription={t("console.operations.emptyDescription")}
      loading={isLoading}
      minWidth={minWidth}
      rowKey={rowKey}
      {...tableProps}
    />
  );
}

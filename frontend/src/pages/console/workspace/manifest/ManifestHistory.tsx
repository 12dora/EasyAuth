/** 查询并渲染 Manifest 版本历史表格。 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { AppTable, useServerTable, type ColumnsType } from "../../../../components/antd/AppTable";
import { dateTimeColumn, textColumn } from "../../../../components/antd/columns";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import { manifestVersionsQueryPrefix, type ManifestVersion } from "./manifestImportModel";

export function useManifestHistory(appKey: string) {
  // 版本历史接口只认 page/page_size, 没有排序参数: serializeSort 置空,
  // 表头排序退化为 antd 对当前页的客户端排序。
  const serverTable = useServerTable<ManifestVersion>({
    defaultPageSize: 20,
    serializeSort: () => ({}),
  });
  const { page, page_size: pageSize } = serverTable.params;
  const queryPrefix = manifestVersionsQueryPrefix(appKey);
  const query = useQuery({
    queryKey: [...queryPrefix, page, pageSize],
    queryFn: () =>
      apiRequest<ListPayload<ManifestVersion>>(
        `/console/api/v1/apps/${appKey}/permission-template-versions?page=${page}&page_size=${pageSize}`,
      ),
  });
  serverTable.setTotal(query.data?.pagination?.total_items);
  return { query, serverTable };
}

export function ManifestHistory({ state }: { state: ReturnType<typeof useManifestHistory> }) {
  const { query, serverTable } = state;
  const columns = useMemo<ColumnsType<ManifestVersion>>(
    () => [
      textColumn<ManifestVersion>({
        key: "version",
        title: "版本",
        getValue: (row) => row.catalog_version ?? row.version,
        mono: true,
        sorter: true,
        width: 200,
      }),
      dateTimeColumn<ManifestVersion>({
        key: "imported_at",
        title: "导入时间",
        getValue: (row) => row.imported_at ?? row.created_at,
      }),
      textColumn<ManifestVersion>({ key: "imported_by", title: "导入人", sorter: true }),
    ],
    [],
  );

  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold text-ink">版本历史</h2>
      <AppTable<ManifestVersion>
        {...serverTable.tableProps}
        columns={columns}
        dataSource={itemsFromPayload<ManifestVersion>(query.data)}
        emptyDescription="确认导入清单后会在这里记录版本。"
        emptyTitle="暂无版本历史"
        loading={query.isLoading}
        rowKey={(row) => `${row.catalog_version ?? row.version ?? ""}:${row.imported_at ?? row.created_at ?? ""}`}
      />
    </div>
  );
}

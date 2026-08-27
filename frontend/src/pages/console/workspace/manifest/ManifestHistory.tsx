/** 查询并渲染 Manifest 版本历史表格。 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  AppTable,
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
  type ColumnsType,
} from "../../../../components/antd/AppTable";
import { dateTimeColumn, serverSortColumn, textColumn } from "../../../../components/antd/columns";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import { manifestVersionsQueryPrefix, type ManifestVersion } from "./manifestImportModel";

/**
 * 列 key -> 后端 `ordering` 字段。接口另外允许 `imported_at`, 但版本项的 payload
 * (`template_version_item`)根本不下发导入时间, 那一列永远是 "-", 排它没有意义,
 * 因此只保留版本一列可排。导入人后端排不了。
 */
const MANIFEST_ORDERING_FIELDS = { version: "version" } as const;

export function useManifestHistory(appKey: string) {
  const serverTable = useServerTable<ManifestVersion>({
    defaultPageSize: 20,
    sortParam: ORDERING_PARAM,
    serializeSort: orderingSerializer(MANIFEST_ORDERING_FIELDS),
  });
  const queryPrefix = manifestVersionsQueryPrefix(appKey);
  // ordering 必须一起进查询串和查询键, 否则点了表头也不会重新请求。
  const versionsSearch = serverTableQuery(serverTable.params);
  const query = useQuery({
    queryKey: [...queryPrefix, versionsSearch],
    queryFn: () =>
      apiRequest<ListPayload<ManifestVersion>>(
        `/console/api/v1/apps/${appKey}/permission-template-versions?${versionsSearch}`,
      ),
  });
  serverTable.setTotal(query.data?.pagination?.total_items);
  return { query, serverTable };
}

export function ManifestHistory({ state }: { state: ReturnType<typeof useManifestHistory> }) {
  const { query, serverTable } = state;
  const sort = serverTable.query;
  const columns = useMemo<ColumnsType<ManifestVersion>>(
    () => [
      serverSortColumn(
        textColumn<ManifestVersion>({
          key: "version",
          title: "版本",
          getValue: (row) => row.catalog_version ?? row.version,
          mono: true,
          width: 200,
        }),
        sort,
      ),
      // 导入时间与导入人后端都排不了(前者 payload 里压根没有), 因此不给 sorter:
      // 客户端比较函数只会重排当前页, 与「共 N 条」自相矛盾。
      dateTimeColumn<ManifestVersion>({
        key: "imported_at",
        title: "导入时间",
        getValue: (row) => row.imported_at ?? row.created_at,
        sorter: false,
      }),
      textColumn<ManifestVersion>({ key: "imported_by", title: "导入人" }),
    ],
    [sort],
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
        // 固定列 200(版本) + 170(导入时间) = 370, 唯一的弹性列(导入人)留 240 -> 610。
        minWidth={610}
        rowKey={(row) => `${row.catalog_version ?? row.version ?? ""}:${row.imported_at ?? row.created_at ?? ""}`}
      />
    </div>
  );
}

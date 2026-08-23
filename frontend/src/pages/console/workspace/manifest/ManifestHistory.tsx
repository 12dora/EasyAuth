/** 查询并渲染 Manifest 版本历史表格。 */

import { getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { EmptyState } from "../../../../components/ui/EmptyState";
import { TableView } from "../../../../components/ui/TableView";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import { manifestVersionsQueryPrefix, type ManifestVersion } from "./manifestImportModel";

export function useManifestHistory(appKey: string) {
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 20 });
  const queryPrefix = manifestVersionsQueryPrefix(appKey);
  const query = useQuery({
    queryKey: [...queryPrefix, pagination.pageIndex, pagination.pageSize],
    queryFn: () =>
      apiRequest<ListPayload<ManifestVersion>>(
        `/console/api/v1/apps/${appKey}/permission-template-versions?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`,
      ),
  });
  const columns: ColumnDef<ManifestVersion>[] = [
    { header: "版本", cell: ({ row }) => row.original.catalog_version ?? row.original.version ?? "-" },
    { header: "导入时间", cell: ({ row }) => row.original.imported_at ?? row.original.created_at ?? "-" },
    { header: "导入人", cell: ({ row }) => row.original.imported_by ?? "-" },
  ];
  const table = useReactTable({
    data: itemsFromPayload<ManifestVersion>(query.data),
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: query.data?.pagination?.total_pages ?? 1,
    state: { pagination },
    onPaginationChange: setPagination,
  });
  return { query, table };
}

export function ManifestHistory({ state }: { state: ReturnType<typeof useManifestHistory> }) {
  return (
    <div className="space-y-3">
      <h2 className="text-base font-semibold text-ink">版本历史</h2>
      <TableView
        table={state.table}
        totalItems={state.query.data?.pagination?.total_items ?? 0}
        isLoading={state.query.isLoading}
        empty={<EmptyState title="暂无版本历史" description="确认导入清单后会在这里记录版本。" />}
      />
    </div>
  );
}

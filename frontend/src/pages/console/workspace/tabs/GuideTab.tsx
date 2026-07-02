import { useQuery } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { CodeBlock } from "../../../../components/CodeBlock";
import { apiRequest } from "../../../../lib/api";
import type { IntegrationGuide } from "../../../../lib/domain";

type CredentialModeRow = NonNullable<IntegrationGuide["credential_modes"]>[number];

export function GuideTab({ appKey }: { appKey: string }) {
  const guideQuery = useQuery({
    queryKey: ["console", "app", appKey, "integration-guide"],
    queryFn: () => apiRequest<IntegrationGuide>(`/console/api/v1/apps/${appKey}/integration-guide`),
  });
  const credentialModeColumns: ColumnDef<CredentialModeRow>[] = [
    { header: "模式", cell: ({ row }) => row.original.mode },
    { header: "活跃数量", cell: ({ row }) => row.original.active_count },
  ];
  const credentialModeTable = useReactTable({
    data: guideQuery.data?.credential_modes ?? [],
    columns: credentialModeColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const endpoint = guideQuery.data?.permission_query_endpoint ?? `/api/v1/apps/${appKey}/users/{user_id}/permissions`;
  const curl = `curl -H "Authorization: Bearer $APP_TOKEN" "${endpoint}"`;
  const ts = `await fetch("${endpoint}", {\n  headers: { Authorization: \`Bearer \${appToken}\` },\n});`;

  return (
    <section className="space-y-6">
      <TableFrame>
        <TableRoot>
          <TableHead>
            {credentialModeTable.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHeaderCell key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHeaderCell>
                ))}
              </TableRow>
            ))}
          </TableHead>
          <TableBody>
            {credentialModeTable.getRowModel().rows.length > 0 ? (
              credentialModeTable.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmptyRow colSpan={credentialModeColumns.length}>
                  {guideQuery.isLoading ? "加载中" : "暂无活跃凭据"}
                </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={credentialModeTable} />
      </TableFrame>
      <CodeBlock language="curl" code={curl} />
      <CodeBlock language="typescript" code={ts} />
    </section>
  );
}

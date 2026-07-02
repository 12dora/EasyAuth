import { useMutation } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { Play } from "lucide-react";
import { useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
import { Field, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { Toast } from "../../../../components/Toast";
import { apiRequest } from "../../../../lib/api";
import type { QueryTestResult } from "../../../../lib/domain";

type QueryTestGroup = { key?: string; name?: string; source?: string; snapshot_version?: string };
type QueryTestGrant = {
  permission?: string;
  scope?: string;
  source_type?: string;
  source_key?: string;
  name?: string;
  snapshot_version?: string;
  grant_type?: string;
};
type StructuredQueryTestResult = QueryTestResult & {
  source?: string;
  snapshot_version?: string;
  groups?: QueryTestGroup[];
  grants?: QueryTestGrant[];
};

export function QueryTestTab({ appKey }: { appKey: string }) {
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<StructuredQueryTestResult | null>(null);
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<StructuredQueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
        method: "POST",
        body: { user_id: userId, token },
      }),
    onSuccess: (payload) => {
      setResult(payload);
      setToken("");
    },
  });
  const groupColumns: ColumnDef<QueryTestGroup>[] = [
    { header: "授权组", cell: ({ row }) => row.original.key ?? "-" },
    { header: "名称", cell: ({ row }) => row.original.name ?? "-" },
    { header: "来源", cell: ({ row }) => row.original.source ?? "-" },
    { header: "快照版本", cell: ({ row }) => row.original.snapshot_version ?? result?.snapshot_version ?? "-" },
  ];
  const grantColumns: ColumnDef<QueryTestGrant>[] = [
    { header: "授权项", cell: ({ row }) => row.original.permission ?? "-" },
    { header: "Scope", cell: ({ row }) => row.original.scope ?? "-" },
    { header: "名称", cell: ({ row }) => row.original.name ?? "-" },
    { header: "类型", cell: ({ row }) => row.original.grant_type ?? "-" },
    {
      header: "来源",
      cell: ({ row }) => (row.original.source_key ? `${row.original.source_type ?? "-"}:${row.original.source_key}` : row.original.source_type ?? "-"),
    },
    { header: "快照版本", cell: ({ row }) => row.original.snapshot_version ?? result?.snapshot_version ?? "-" },
  ];
  const groupTable = useReactTable({
    data: result?.groups ?? [],
    columns: groupColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const grantTable = useReactTable({
    data: result?.grants ?? [],
    columns: grantColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Field label="用户 ID">
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} />
        </Field>
        <Field label="Bearer token">
          <TextInput type="password" value={token} onChange={(event) => setToken(event.currentTarget.value)} autoComplete="off" />
        </Field>
        <Button variant="primary" icon={<Play size={16} />} disabled={!userId || !token} onClick={() => testMutation.mutate()}>
          执行联调
        </Button>
      </PanelSurface>
      {testMutation.error ? <StatusBanner tone="signal" title="联调失败" message={(testMutation.error as Error).message} /> : null}
      {result ? (
        <>
          <Toast tone="evergreen" message={result.allowed ? "权限查询命中授权" : "查询成功，无授权命中"} />
          <div className="grid gap-3 sm:grid-cols-2">
            <PanelSurface>
              <span className="text-xs font-semibold text-ink-faint">source</span>
              <strong className="mt-2 block text-sm font-semibold text-ink">来源：{result.source ?? "-"}</strong>
            </PanelSurface>
            <PanelSurface>
              <span className="text-xs font-semibold text-ink-faint">snapshot_version</span>
              <strong className="mt-2 block text-sm font-semibold text-ink">快照版本：{result.snapshot_version ?? result.version ?? "-"}</strong>
            </PanelSurface>
          </div>
          <TableFrame>
            <TableRoot>
              <TableHead>
                {groupTable.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHeaderCell key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHeaderCell>
                    ))}
                  </TableRow>
                ))}
              </TableHead>
              <TableBody>
                {groupTable.getRowModel().rows.length > 0 ? (
                  groupTable.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={groupColumns.length}>
                      暂无授权组
                    </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination table={groupTable} />
          </TableFrame>
          <TableFrame>
            <TableRoot>
              <TableHead>
                {grantTable.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHeaderCell key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHeaderCell>
                    ))}
                  </TableRow>
                ))}
              </TableHead>
              <TableBody>
                {grantTable.getRowModel().rows.length > 0 ? (
                  grantTable.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={grantColumns.length}>
                      暂无授权项
                    </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination table={grantTable} />
          </TableFrame>
          <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
        </>
      ) : null}
    </section>
  );
}

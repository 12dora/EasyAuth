import { useQuery } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { RotateCw, ShieldOff } from "lucide-react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { SecretDialog } from "../../../../components/SecretDialog";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { CredentialItem } from "../../../../lib/domain";
import { CreateCredentialForm } from "../credentials/CreateCredentialForm";
import { useCredentialsActions } from "../credentials/useCredentialsActions";
import { credentialKindLabel } from "../utils";

export function CredentialsTab({ appKey }: { appKey: string }) {
  const credentialsQuery = useQuery({
    queryKey: ["console", "app", appKey, "credentials"],
    queryFn: () => apiRequest<{ items?: CredentialItem[] }>(`/console/api/v1/apps/${appKey}/credentials`),
  });
  const credentials = itemsFromPayload<CredentialItem>(credentialsQuery.data);
  const { createCredential, rotateCredential, disableCredential, operationError, secretEntries, closeSecretDialog } =
    useCredentialsActions(appKey);
  const credentialColumns: ColumnDef<CredentialItem>[] = [
    { header: "名称", accessorKey: "name" },
    { header: "类型", cell: ({ row }) => credentialKindLabel(row.original.kind) },
    {
      header: "client_id",
      cell: ({ row }) => (row.original.client_id ? <code>{row.original.client_id}</code> : "-"),
    },
    {
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge>
      ),
    },
    {
      header: "操作",
      cell: ({ row }) => (
        <div className="flex items-center gap-2">
          {row.original.kind === "static_token" ? (
            <Button
              variant="ghost"
              size="sm"
              icon={<RotateCw size={14} />}
              onClick={() => rotateCredential(row.original.id)}
              aria-label="轮换"
            />
          ) : null}
          <Button
            variant="ghost-danger"
            size="sm"
            icon={<ShieldOff size={14} />}
            onClick={() => disableCredential(row.original)}
            aria-label="禁用"
          />
        </div>
      ),
    },
  ];
  const credentialTable = useReactTable({
    data: credentials,
    columns: credentialColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <section className="space-y-6">
      <CreateCredentialForm onCreateCredential={createCredential} />
      {operationError ? (
        <StatusBanner tone="signal" title="凭据操作失败" message={(operationError as Error).message} />
      ) : null}
      <TableFrame>
        <TableRoot>
          <TableHead>
            {credentialTable.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHeaderCell key={header.id}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHeaderCell>
                ))}
              </TableRow>
            ))}
          </TableHead>
          <TableBody>
            {credentialTable.getRowModel().rows.length > 0 ? (
              credentialTable.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmptyRow colSpan={credentialColumns.length}>
                  {credentialsQuery.isLoading ? "加载中" : "暂无凭据"}
                </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
      </TableFrame>
      {secretEntries[0] ? (
        <SecretDialog
          title="一次性凭据"
          primaryLabel={secretEntries[0][0]}
          primaryValue={secretEntries[0][1]}
          secondaryLabel={secretEntries[1]?.[0]}
          secondaryValue={secretEntries[1]?.[1]}
          onClose={closeSecretDialog}
        />
      ) : null}
    </section>
  );
}

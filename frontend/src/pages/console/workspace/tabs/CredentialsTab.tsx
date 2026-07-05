import { useQuery } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { Fragment } from "react";
import { Plus } from "lucide-react";
import { useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../../../components/ui/TablePrimitives";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { SecretDialog } from "../../../../components/SecretDialog";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type { CredentialItem } from "../../../../lib/domain";
import { CreateCredentialForm } from "../credentials/CreateCredentialForm";
import { useCredentialsActions } from "../credentials/useCredentialsActions";
import { credentialKindLabel } from "../utils";

export function CredentialsTab({ appKey }: { appKey: string }) {
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const credentialsQuery = useQuery({
    queryKey: ["console", "app", appKey, "credentials"],
    queryFn: () => apiRequest<ListPayload<CredentialItem>>(`/console/api/v1/apps/${appKey}/credentials`),
  });
  const credentials = itemsFromPayload<CredentialItem>(credentialsQuery.data);
  const { createCredential, isCreating, rotateCredential, disableCredential, operationError, secretEntries, closeSecretDialog } =
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
      id: "actions",
      header: "操作",
      cell: ({ row }) => (
        <TableActionCell>
          {row.original.kind === "static_token" ? (
            <TableRowActionButton
              type="button"
              onClick={() => rotateCredential(row.original.id)}
            >
              轮换
            </TableRowActionButton>
          ) : null}
          <TableRowActionButton
            type="button"
            variant="ghost-danger"
            onClick={() => disableCredential(row.original)}
          >
            禁用
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const credentialTable = useReactTable({
    data: credentials,
    columns: credentialColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">凭据</h2>
        <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => setCreateDialogOpen(true)}>
          新建
        </Button>
      </div>
      {credentialsQuery.error ? (
        <StatusBanner tone="signal" title="凭据加载失败" message={(credentialsQuery.error as Error).message} />
      ) : null}
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
            {credentialsQuery.isLoading ? (
              <TableSkeletonRows columns={credentialColumns.length} />
            ) : credentialTable.getRowModel().rows.length > 0 ? (
              credentialTable.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    cell.column.id === "actions" ? (
                      <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                    ) : (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    )
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmptyRow colSpan={credentialColumns.length}>
                <EmptyState title="暂无凭据" description="新建凭据后，应用即可调用权限查询接口。" />
              </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={credentialTable} />
      </TableFrame>
      {createDialogOpen ? (
        <Dialog title="新建凭据" onClose={() => setCreateDialogOpen(false)}>
          <CreateCredentialForm
            isCreating={isCreating}
            onCreateCredential={async (kind, name) => {
              await createCredential(kind, name);
              setCreateDialogOpen(false);
            }}
          />
        </Dialog>
      ) : null}
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

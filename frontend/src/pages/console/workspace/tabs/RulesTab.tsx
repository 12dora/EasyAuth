import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Fragment, useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../../../components/ui/TablePrimitives";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ApprovalRuleItem } from "../../../../lib/domain";
import { safeJoin } from "../utils";

type RuleTargetType = "authorization_group" | "permission";
type EditableApprovalRule = ApprovalRuleItem & { blocking?: boolean; status?: string };

const emptyForm = {
  target_type: "authorization_group" as RuleTargetType,
  target_key: "",
  approver_userids: "",
};

export function RulesTab({ appKey }: { appKey: string }) {
  const queryClient = useQueryClient();
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [dialogOpen, setDialogOpen] = useState(false);
  const queryKey = ["console", "app", appKey, "approval-rules"];
  const rulesQuery = useQuery({
    queryKey,
    queryFn: () => apiRequest<{ data?: EditableApprovalRule[] }>(`/console/api/v1/apps/${appKey}/approval-rules`),
  });
  const rules = itemsFromPayload<EditableApprovalRule>(rulesQuery.data);
  const saveMutation = useMutation({
    mutationFn: () => {
      const body = {
        target_type: form.target_type,
        target_key: form.target_key,
        approver_userids: splitUserids(form.approver_userids),
      };
      if (editingRuleId) {
        return apiRequest(`/console/api/v1/apps/${appKey}/approval-rules/${editingRuleId}`, {
          method: "PATCH",
          body,
        });
      }
      return apiRequest(`/console/api/v1/apps/${appKey}/approval-rules`, {
        method: "POST",
        body,
      });
    },
    onSuccess: async () => {
      setEditingRuleId(null);
      setForm(emptyForm);
      setDialogOpen(false);
      await queryClient.invalidateQueries({ queryKey });
    },
  });
  const toggleMutation = useMutation({
    mutationFn: (rule: EditableApprovalRule) =>
      apiRequest(`/console/api/v1/apps/${appKey}/approval-rules/${rule.id}`, {
        method: "PATCH",
        body: {
          is_active: !rule.is_active,
        },
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });
  const ruleColumns: ColumnDef<EditableApprovalRule>[] = [
    { header: "对象", cell: ({ row }) => `${targetTypeLabel(row.original.target_type)}：${row.original.target_key ?? "-"}` },
    { header: "审批人", cell: ({ row }) => safeJoin(row.original.approver_userids) },
    {
      header: "状态",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? "启用" : "停用"}</Badge>
          {isBlocking(row.original) ? <Badge tone="signal">阻塞</Badge> : null}
        </div>
      ),
    },
    {
      id: "actions",
      header: "操作",
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton
            type="button"
            onClick={() => {
              setEditingRuleId(row.original.id);
              setForm({
                target_type: normalizeTargetType(row.original.target_type),
                target_key: row.original.target_key ?? "",
                approver_userids: (row.original.approver_userids ?? []).join(","),
              });
              setDialogOpen(true);
            }}
          >
            编辑
          </TableRowActionButton>
          <TableRowActionButton
            type="button"
            variant={row.original.is_active ? "ghost-danger" : "ghost"}
            onClick={() => toggleMutation.mutate(row.original)}
            disabled={toggleMutation.isPending}
          >
            {row.original.is_active ? "停用" : "启用"}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const ruleTable = useReactTable({
    data: rules,
    columns: ruleColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">审批规则</h2>
        <Button
          type="button"
          variant="primary"
          icon={<Plus size={16} />}
          onClick={() => {
            setEditingRuleId(null);
            setForm(emptyForm);
            setDialogOpen(true);
          }}
        >
          新建
        </Button>
      </div>
      {rulesQuery.error ? <StatusBanner tone="signal" title="审批规则加载失败" message={(rulesQuery.error as Error).message} /> : null}
      {saveMutation.error ? <StatusBanner tone="signal" title="审批规则保存失败" message={(saveMutation.error as Error).message} /> : null}
      {toggleMutation.error ? <StatusBanner tone="signal" title="审批规则状态更新失败" message={(toggleMutation.error as Error).message} /> : null}
      <TableFrame>
        <TableRoot>
          <TableHead>
            {ruleTable.getHeaderGroups().map((headerGroup) => (
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
            {rulesQuery.isLoading ? (
              <TableSkeletonRows columns={ruleTable.getAllLeafColumns().length} />
            ) : ruleTable.getRowModel().rows.length > 0 ? (
              ruleTable.getRowModel().rows.map((row) => (
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
              <TableEmptyRow colSpan={ruleTable.getAllLeafColumns().length}>
                <EmptyState title="暂无审批规则" description="新建规则后，对应权限申请将走指定审批人。" />
              </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={ruleTable} />
      </TableFrame>
      {dialogOpen ? (
        <Dialog title={editingRuleId ? "编辑审批规则" : "新建审批规则"} onClose={() => setDialogOpen(false)} footer={
          <>
            <Button type="button" onClick={() => setDialogOpen(false)}>取消</Button>
            <Button
              form="approval-rule-form"
              type="submit"
              variant="primary"
              loading={saveMutation.isPending}
              disabled={!form.target_key || !form.approver_userids || saveMutation.isPending}
            >
              保存
            </Button>
          </>
        }>
          <form id="approval-rule-form" className="grid gap-4" onSubmit={(event) => {
            event.preventDefault();
            saveMutation.mutate();
          }}>
            <Field label="规则目标类型">
              <SelectInput
                aria-label="规则目标类型"
                value={form.target_type}
                onChange={(event) => {
                  const targetType = event.currentTarget.value as RuleTargetType;
                  setForm((current) => ({ ...current, target_type: targetType }));
                }}
              >
                <option value="authorization_group">授权组（authorization_group）</option>
                <option value="permission">权限（permission）</option>
              </SelectInput>
            </Field>
            <Field label="目标 Key">
              <TextInput
                aria-label="目标 Key"
                value={form.target_key}
                onChange={(event) => {
                  const targetKey = event.currentTarget.value;
                  setForm((current) => ({ ...current, target_key: targetKey }));
                }}
              />
            </Field>
            <Field label="审批人 user_id" hint="多个审批人用英文逗号分隔">
              <TextInput
                aria-label="审批人 user_id"
                value={form.approver_userids}
                onChange={(event) => {
                  const approverUserids = event.currentTarget.value;
                  setForm((current) => ({ ...current, approver_userids: approverUserids }));
                }}
              />
            </Field>
          </form>
        </Dialog>
      ) : null}
    </section>
  );
}

function splitUserids(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function targetTypeLabel(value: string | undefined): string {
  if (value === "permission") {
    return "权限";
  }
  if (value === "authorization_group") {
    return "授权组";
  }
  return value ?? "-";
}

function normalizeTargetType(value: string | undefined): RuleTargetType {
  return value === "permission" ? "permission" : "authorization_group";
}

function isBlocking(rule: EditableApprovalRule): boolean {
  return rule.blocking === true || rule.status === "blocking";
}

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Edit3, Save, ToggleLeft, ToggleRight } from "lucide-react";
import { useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
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
  const queryKey = ["console", "app", appKey, "approval-rules"];
  const rulesQuery = useQuery({
    queryKey,
    queryFn: () => apiRequest<{ items?: EditableApprovalRule[] }>(`/console/api/v1/apps/${appKey}/approval-rules`),
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
    { header: "对象", cell: ({ row }) => `${row.original.target_type ?? "-"}:${row.original.target_key ?? "-"}` },
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
      header: "操作",
      cell: ({ row }) => (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            icon={<Edit3 size={16} />}
            onClick={() => {
              setEditingRuleId(row.original.id);
              setForm({
                target_type: normalizeTargetType(row.original.target_type),
                target_key: row.original.target_key ?? "",
                approver_userids: (row.original.approver_userids ?? []).join(","),
              });
            }}
          >
            编辑
          </Button>
          <Button
            icon={row.original.is_active ? <ToggleLeft size={16} /> : <ToggleRight size={16} />}
            onClick={() => toggleMutation.mutate(row.original)}
            disabled={toggleMutation.isPending}
          >
            {row.original.is_active ? "停用" : "启用"}
          </Button>
        </div>
      ),
    },
  ];
  const ruleTable = useReactTable({
    data: rules,
    columns: ruleColumns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="grid items-end gap-4 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.3fr)_auto]">
        <Field label="规则目标类型">
          <SelectInput
            aria-label="规则目标类型"
            value={form.target_type}
            onChange={(event) => {
              const targetType = event.currentTarget.value as RuleTargetType;
              setForm((current) => ({ ...current, target_type: targetType }));
            }}
          >
            <option value="authorization_group">authorization_group</option>
            <option value="permission">permission</option>
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
        <Button
          variant="primary"
          icon={<Save size={16} />}
          disabled={!form.target_key || !form.approver_userids || saveMutation.isPending}
          onClick={() => saveMutation.mutate()}
        >
          {editingRuleId ? "保存规则" : "新建规则"}
        </Button>
      </div>
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
            {ruleTable.getRowModel().rows.length > 0 ? (
              ruleTable.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableEmptyRow colSpan={ruleTable.getAllLeafColumns().length}>
                  {rulesQuery.isLoading ? "加载中" : "暂无审批规则"}
                </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
      </TableFrame>
    </section>
  );
}

function splitUserids(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeTargetType(value: string | undefined): RuleTargetType {
  return value === "permission" ? "permission" : "authorization_group";
}

function isBlocking(rule: EditableApprovalRule): boolean {
  return rule.blocking === true || rule.status === "blocking";
}

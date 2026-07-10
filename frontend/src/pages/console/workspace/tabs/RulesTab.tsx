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
import { useToast } from "../../../../components/ui/Toast";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { ApprovalRuleItem } from "../../../../lib/domain";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { Translator } from "../../../../lib/status";
import { safeJoin } from "../utils";

type RuleTargetType = "authorization_group" | "permission";
type EditableApprovalRule = ApprovalRuleItem & { blocking?: boolean; status?: string };

const emptyForm = {
  target_type: "authorization_group" as RuleTargetType,
  target_key: "",
  approver_userids: "",
};

export function RulesTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const toast = useToast();
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
    onError: (error: Error) => {
      toast.error(t("console.rules.saveFailed"), error.message);
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
    onError: (error: Error) => {
      toast.error(t("console.rules.toggleFailed"), error.message);
    },
  });
  const ruleColumns: ColumnDef<EditableApprovalRule>[] = [
    { header: t("console.rules.column.target"), cell: ({ row }) => `${targetTypeLabel(t, row.original.target_type)}：${row.original.target_key ?? "-"}` },
    { header: t("console.rules.column.approvers"), cell: ({ row }) => safeJoin(row.original.approver_userids) },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? t("common.enabled") : t("common.disabled")}</Badge>
          {isBlocking(row.original) ? <Badge tone="signal">{t("console.rules.blocking")}</Badge> : null}
        </div>
      ),
    },
    {
      id: "actions",
      header: t("common.actions"),
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
            {t("common.edit")}
          </TableRowActionButton>
          <TableRowActionButton
            type="button"
            variant={row.original.is_active ? "ghost-danger" : "ghost"}
            onClick={() => toggleMutation.mutate(row.original)}
            disabled={toggleMutation.isPending}
          >
            {row.original.is_active ? t("common.disable") : t("common.enable")}
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
        <h2 className="text-base font-semibold text-ink">{t("console.rules.heading")}</h2>
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
          {t("common.new")}
        </Button>
      </div>
      {rulesQuery.error ? <StatusBanner tone="signal" title={t("console.rules.loadFailed")} message={(rulesQuery.error as Error).message} /> : null}
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
                <EmptyState title={t("console.rules.empty")} description={t("console.rules.emptyDescription")} />
              </TableEmptyRow>
            )}
          </TableBody>
        </TableRoot>
        <TablePagination table={ruleTable} totalItems={rules.length} />
      </TableFrame>
      {dialogOpen ? (
        <Dialog title={editingRuleId ? t("console.rules.editTitle") : t("console.rules.createTitle")} onClose={() => setDialogOpen(false)} footer={
          <>
            <Button type="button" onClick={() => setDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button
              form="approval-rule-form"
              type="submit"
              variant="primary"
              loading={saveMutation.isPending}
              disabled={!form.target_key || !form.approver_userids || saveMutation.isPending}
            >
              {t("common.save")}
            </Button>
          </>
        }>
          <form id="approval-rule-form" className="grid gap-4" onSubmit={(event) => {
            event.preventDefault();
            saveMutation.mutate();
          }}>
            <Field label={t("console.rules.targetTypeLabel")}>
              <SelectInput
                aria-label={t("console.rules.targetTypeLabel")}
                value={form.target_type}
                onChange={(event) => {
                  const targetType = event.currentTarget.value as RuleTargetType;
                  setForm((current) => ({ ...current, target_type: targetType }));
                }}
              >
                <option value="authorization_group">{t("console.rules.targetOption.authorizationGroup")}</option>
                <option value="permission">{t("console.rules.targetOption.permission")}</option>
              </SelectInput>
            </Field>
            <Field label={t("console.rules.targetKey")}>
              <TextInput
                aria-label={t("console.rules.targetKey")}
                value={form.target_key}
                onChange={(event) => {
                  const targetKey = event.currentTarget.value;
                  setForm((current) => ({ ...current, target_key: targetKey }));
                }}
              />
            </Field>
            <Field label={t("console.rules.approverField")} hint={t("console.rules.approverHint")}>
              <TextInput
                aria-label={t("console.rules.approverField")}
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

function targetTypeLabel(t: Translator, value: string | undefined): string {
  if (value === "permission") {
    return t("console.rules.targetType.permission");
  }
  if (value === "authorization_group") {
    return t("console.rules.targetType.authorizationGroup");
  }
  return value ?? "-";
}

function normalizeTargetType(value: string | undefined): RuleTargetType {
  return value === "permission" ? "permission" : "authorization_group";
}

function isBlocking(rule: EditableApprovalRule): boolean {
  return rule.blocking === true || rule.status === "blocking";
}

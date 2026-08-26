import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { AppTable, enumFilter, type ColumnsType } from "../../../../components/antd/AppTable";
import { RowActionButton, actionsColumn, textColumn } from "../../../../components/antd/columns";
import { EmptyState } from "../../../../components/ui/EmptyState";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { UserMultiSelect } from "../../../../components/UserSelect";
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
  approverUserIds: [] as string[],
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
        approver_userids: form.approverUserIds,
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
  const ruleColumns: ColumnsType<EditableApprovalRule> = [
    textColumn<EditableApprovalRule>({
      key: "target",
      title: t("console.rules.column.target"),
      getValue: (rule) => `${targetTypeLabel(t, rule.target_type)}\uff1a${rule.target_key ?? "-"}`,
      filter: true,
      sorter: true,
      width: 280,
    }),
    textColumn<EditableApprovalRule>({
      key: "approvers",
      title: t("console.rules.column.approvers"),
      getValue: (rule) => safeJoin(rule.approver_userids),
      filter: true,
    }),
    {
      key: "status",
      title: t("common.status"),
      width: 180,
      render: (_value: unknown, rule: EditableApprovalRule) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={rule.is_active ? "evergreen" : "neutral"}>{rule.is_active ? t("common.enabled") : t("common.disabled")}</Badge>
          {isBlocking(rule) ? <Badge tone="signal">{t("console.rules.blocking")}</Badge> : null}
        </div>
      ),
      // 单元格里可能同时有「启用」和「阻塞」两枚徽章, 因此筛选值是数组, 按「包含」匹配。
      ...enumFilter<EditableApprovalRule>(
        "status",
        [
          { label: t("common.enabled"), value: "active" },
          { label: t("common.disabled"), value: "inactive" },
          { label: t("console.rules.blocking"), value: "blocking" },
        ],
        {
          getValue: (rule) => [rule.is_active ? "active" : "inactive", ...(isBlocking(rule) ? ["blocking"] : [])],
        },
      ),
    },
    actionsColumn<EditableApprovalRule>({
      title: t("common.actions"),
      render: (rule) => (
        <>
          <RowActionButton
            type="button"
            onClick={() => {
              setEditingRuleId(rule.id);
              setForm({
                target_type: normalizeTargetType(rule.target_type),
                target_key: rule.target_key ?? "",
                approverUserIds: rule.approver_userids ?? [],
              });
              setDialogOpen(true);
            }}
          >
            {t("common.edit")}
          </RowActionButton>
          <RowActionButton
            type="button"
            variant={rule.is_active ? "ghost-danger" : "ghost"}
            onClick={() => toggleMutation.mutate(rule)}
            disabled={toggleMutation.isPending}
          >
            {rule.is_active ? t("common.disable") : t("common.enable")}
          </RowActionButton>
        </>
      ),
    }),
  ];

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
      {rulesQuery.error ? <StatusBanner live="alert" tone="signal" title={t("console.rules.loadFailed")} message={(rulesQuery.error as Error).message} /> : null}
      <AppTable<EditableApprovalRule>
        columns={ruleColumns}
        dataSource={rules}
        rowKey="id"
        loading={rulesQuery.isLoading}
        minWidth={880}
        empty={<EmptyState title={t("console.rules.empty")} description={t("console.rules.emptyDescription")} />}
      />
      {dialogOpen ? (
        <Dialog title={editingRuleId ? t("console.rules.editTitle") : t("console.rules.createTitle")} onClose={() => setDialogOpen(false)} footer={
          <>
            <Button type="button" onClick={() => setDialogOpen(false)}>{t("common.cancel")}</Button>
            <Button
              form="approval-rule-form"
              type="submit"
              variant="primary"
              loading={saveMutation.isPending}
              disabled={!form.target_key || form.approverUserIds.length === 0 || saveMutation.isPending}
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
              <UserMultiSelect
                aria-label={t("console.rules.approverField")}
                value={form.approverUserIds}
                onChange={(approverUserIds) => setForm((current) => ({ ...current, approverUserIds }))}
                searchPurpose="approver"
              />
            </Field>
          </form>
        </Dialog>
      ) : null}
    </section>
  );
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

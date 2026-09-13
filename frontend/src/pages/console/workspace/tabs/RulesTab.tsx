import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { AppTable } from "../../../../components/antd/AppTable";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useUserOptionsByIds } from "../../../../components/UserCombobox";
import { useToast } from "../../../../components/ui/Toast";
import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import { useI18n } from "../../../../i18n/I18nProvider";
import { RuleEditorDialog } from "./RuleEditorDialog";
import { buildRuleColumns, editFormFromRule } from "./rulesTabColumns";
import { emptyRuleForm, type EditableApprovalRule, type RuleFormState } from "./rulesTabModel";

export function RulesTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [editingRuleId, setEditingRuleId] = useState<number | null>(null);
  const [form, setForm] = useState<RuleFormState>(emptyRuleForm);
  const [dialogOpen, setDialogOpen] = useState(false);
  const queryKey = ["console", "app", appKey, "approval-rules"];
  const rulesQuery = useQuery({
    queryKey,
    queryFn: () => apiRequest<{ data?: EditableApprovalRule[] }>(`/console/api/v1/apps/${appKey}/approval-rules`),
  });
  const rules = itemsFromPayload<EditableApprovalRule>(rulesQuery.data);
  const approverIds = useMemo(
    () => [...new Set(rules.flatMap((rule) => rule.approver_userids ?? []))],
    [rules],
  );
  const approverOptionsQuery = useUserOptionsByIds(approverIds, "approver");
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
      setForm(emptyRuleForm);
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
  const ruleColumns = buildRuleColumns({
    approverOptions: approverOptionsQuery.data,
    t,
    onEdit: (rule) => {
      setEditingRuleId(rule.id);
      setForm(editFormFromRule(rule));
      setDialogOpen(true);
    },
    onToggle: (rule) => toggleMutation.mutate(rule),
    togglePending: toggleMutation.isPending,
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
            setForm(emptyRuleForm);
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
        <RuleEditorDialog
          editingRuleId={editingRuleId}
          form={form}
          isSaving={saveMutation.isPending}
          onClose={() => setDialogOpen(false)}
          onFormChange={setForm}
          onSubmit={() => saveMutation.mutate()}
        />
      ) : null}
    </section>
  );
}

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type {
  HandoverGrantItemRow,
  HandoverTaskDetail,
  OnboardingTemplateRow,
  TransferPlanItem,
} from "../../../lib/domain";
import {
  buildGrantNameMap,
  checkedKeys,
  selectionFromEntries,
  transferPlanVersion,
} from "./handoverTaskDetailModel";

/** 转岗权限差异的模板选择、勾选草稿与生成/确认两个 mutation。 */
export function useTransferGrantPlan(task: HandoverTaskDetail, taskId: string, onChanged: () => void) {
  const { t } = useI18n();
  const toast = useToast();
  const plan = task.transfer_plan;
  const [templateId, setTemplateId] = useState(plan?.template_id ? String(plan.template_id) : "");
  const planVersion = transferPlanVersion(plan);
  const initializedPlanVersion = useRef(planVersion);
  const [revokeChecked, setRevokeChecked] = useState<Record<string, boolean>>(() =>
    selectionFromEntries(plan?.grant_diff.revoke ?? []),
  );
  const [addChecked, setAddChecked] = useState<Record<string, boolean>>(() =>
    selectionFromEntries(plan?.grant_diff.add ?? []),
  );

  const templatesQuery = useQuery({
    queryKey: ["console", "onboarding-templates"],
    queryFn: () => apiRequest<ListPayload<OnboardingTemplateRow>>("/console/api/v1/lifecycle/onboarding-templates"),
  });
  const templates = itemsFromPayload<OnboardingTemplateRow>(templatesQuery.data).filter(
    (template) => template.is_active,
  );

  const grantItemsQuery = useQuery({
    queryKey: ["console", "handover-task", taskId, "grant-items"],
    queryFn: () =>
      apiRequest<ListPayload<HandoverGrantItemRow>>(
        `/console/api/v1/lifecycle/handover-tasks/${taskId}/grant-items`,
      ),
  });
  const nameMap = buildGrantNameMap(itemsFromPayload<HandoverGrantItemRow>(grantItemsQuery.data), templates);

  // 同一方案的详情 refetch 不覆盖本地 dirty 选择；仅方案内容实际变化时重新初始化。
  useEffect(() => {
    if (initializedPlanVersion.current === planVersion) {
      return;
    }
    initializedPlanVersion.current = planVersion;
    setRevokeChecked(selectionFromEntries(plan?.grant_diff.revoke ?? []));
    setAddChecked(selectionFromEntries(plan?.grant_diff.add ?? []));
  }, [plan, planVersion]);

  const buildMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ transfer_plan?: TransferPlanItem }>(
        `/console/api/v1/lifecycle/handover-tasks/${taskId}/grant-diff`,
        {
          method: "POST",
          body: { template_id: Number(templateId) } satisfies JsonObject,
        },
      ),
    onSuccess: onChanged,
    onError: (error: Error) => {
      toast.error(t("handover.transfer.diffFailed"), error.message);
    },
  });
  const confirmMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ transfer_plan?: TransferPlanItem }>(
        `/console/api/v1/lifecycle/handover-tasks/${taskId}/grant-diff/confirm`,
        {
          method: "POST",
          body: {
            revoke_keys: checkedKeys(revokeChecked),
            add_keys: checkedKeys(addChecked),
            plan_revision: plan?.revision ?? 0,
          } satisfies JsonObject,
        },
      ),
    onSuccess: onChanged,
    onError: (error: Error) => {
      toast.error(t("handover.transfer.confirmFailed"), error.message);
    },
  });

  return {
    plan,
    templates,
    templatesError: templatesQuery.error,
    templateId,
    setTemplateId,
    nameMap,
    revokeChecked,
    toggleRevoke: (key: string, value: boolean) => setRevokeChecked((current) => ({ ...current, [key]: value })),
    addChecked,
    toggleAdd: (key: string, value: boolean) => setAddChecked((current) => ({ ...current, [key]: value })),
    buildMutation,
    confirmMutation,
  };
}

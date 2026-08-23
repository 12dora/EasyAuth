import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import type { HandoverAction, HandoverTaskPayload } from "../../../lib/domain";
import { shouldPollTaskDetail } from "./handoverTaskDetailModel";

/** 交接任务详情的数据装载与任务级操作(取消/删除/认领/延期)。 */
export function useHandoverTaskDetail(taskId: string) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [wizardOpen, setWizardOpen] = useState(false);
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deferOpen, setDeferOpen] = useState(false);
  const [deferReason, setDeferReason] = useState("");
  const detailQueryKey = ["console", "handover-task", taskId];
  const taskPath = `/console/api/v1/lifecycle/handover-tasks/${taskId}`;

  const taskQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => apiRequest<HandoverTaskPayload>(taskPath),
    enabled: Boolean(taskId),
    refetchInterval: (query) => shouldPollTaskDetail(query.state.data?.handover_task),
  });
  const task = taskQuery.data?.handover_task;
  const invalidateDetail = () => void queryClient.invalidateQueries({ queryKey: detailQueryKey });

  const replaceAction = (next: HandoverAction) => {
    queryClient.setQueryData<HandoverTaskPayload>(detailQueryKey, (current) => {
      if (!current?.handover_task) return current;
      return {
        handover_task: {
          ...current.handover_task,
          actions: current.handover_task.actions.map((a) => (a.app_key === next.app_key ? next : a)),
        },
      };
    });
  };

  const cancelMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>(taskPath, {
        method: "PATCH",
        body: { cancel: true } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(detailQueryKey, payload);
      void queryClient.invalidateQueries({ queryKey: ["console", "handover-tasks"] });
      setCancelConfirmOpen(false);
    },
    onError: (error: Error) => toast.error(t("handover.detail.cancelFailed"), error.message),
  });

  const deleteMutation = useMutation({
    mutationFn: () => apiRequest(taskPath, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "handover-tasks"] });
      void navigate("/console/lifecycle/handover-tasks");
    },
    onError: (error: Error) => toast.error(t("handover.detail.deleteFailed"), error.message),
  });

  const claimMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>(`${taskPath}/claim`, {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(detailQueryKey, payload);
      invalidateDetail();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deferMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>(`${taskPath}/escalation/defer`, {
        method: "POST",
        body: { reason: deferReason.trim() },
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(detailQueryKey, payload);
      setDeferOpen(false);
      setDeferReason("");
      invalidateDetail();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return {
    taskQuery,
    task,
    invalidateDetail,
    replaceAction,
    wizardOpen,
    openWizard: () => setWizardOpen(true),
    closeWizard: () => setWizardOpen(false),
    cancelConfirmOpen,
    openCancelConfirm: () => {
      cancelMutation.reset();
      setCancelConfirmOpen(true);
    },
    closeCancelConfirm: () => setCancelConfirmOpen(false),
    deleteConfirmOpen,
    openDeleteConfirm: () => {
      deleteMutation.reset();
      setDeleteConfirmOpen(true);
    },
    closeDeleteConfirm: () => setDeleteConfirmOpen(false),
    deferOpen,
    openDefer: () => setDeferOpen(true),
    closeDefer: () => setDeferOpen(false),
    deferReason,
    setDeferReason,
    cancelMutation,
    deleteMutation,
    claimMutation,
    deferMutation,
  };
}

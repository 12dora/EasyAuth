import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { ApiError, apiRequest } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { AccessGrantRow } from "../../../lib/domain/accessGrantRow";
import {
  isActiveGrantNotFoundConflict,
  isDecisionCommittedError,
  isDepartmentSourcedGrantConflict,
} from "./operationErrors";
import type {
  AccessRequestAction,
  AccessRequestActionType,
  OperationNotice,
  OperationRow,
} from "./operationRow";

export interface OperationPendingControls {
  setPendingAction: Dispatch<SetStateAction<AccessRequestAction | null>>;
  setPendingRevokeGrant: Dispatch<SetStateAction<AccessGrantRow | null>>;
  setOperationNotice: Dispatch<SetStateAction<OperationNotice | null>>;
}

export function useHealthCheckMutation() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiRequest<ListPayload<OperationRow>>(
        "/console/api/v1/operations/dependency-health/checks",
        { method: "POST" },
      ),
    onSuccess: (payload) => {
      queryClient.setQueryData(["console", "operations", "dependency-health"], payload);
    },
    onError: (error: Error) => {
      toast.error(t("ops.dependencyHealth.runCheckFailed"), error.message);
    },
  });
}

export type AccessRequestMutations = ReturnType<typeof useAccessRequestMutations>;

export function useAccessRequestMutations(controls: OperationPendingControls) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const invalidateAccessRequests = () =>
    queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-requests"] });
  // 409 = 申请状态已变化(如已被处理): 关弹窗、提示冲突并刷新, 其余错误留在弹窗内展示。
  const handleAccessRequestActionError = (error: Error) => {
    if (isDecisionCommittedError(error)) {
      controls.setPendingAction(null);
      controls.setOperationNotice({
        tone: "signal",
        title: t("approvals.grantFailedCommitted"),
        message: t("approvals.grantFailedCommittedDescription"),
      });
      void invalidateAccessRequests();
      return;
    }
    if (error instanceof ApiError && error.status === 409) {
      controls.setPendingAction(null);
      controls.setOperationNotice({ tone: "amber", title: t("approvals.conflict") });
      toast.warning(t("approvals.conflict"));
      void invalidateAccessRequests();
    }
  };
  const onActionSuccess = (successMessage: string) => {
    controls.setPendingAction(null);
    controls.setOperationNotice(null);
    toast.success(successMessage);
    void invalidateAccessRequests();
  };

  const decisionMutation = useMutation({
    mutationFn: ({ type, row, comment }: { type: ApprovalDecisionMode; row: OperationRow; comment: string }) =>
      apiRequest(`/console/api/v1/operations/access-requests/${row.id}/${type}`, {
        method: "POST",
        body: type === "reject" || comment ? { comment } : {},
      }),
    onSuccess: (_, variables) => {
      onActionSuccess(t(variables.type === "approve" ? "approvals.approved" : "approvals.rejected"));
    },
    onError: handleAccessRequestActionError,
  });
  const reassignMutation = useMutation({
    mutationFn: ({ row, approverUserIds }: { row: OperationRow; approverUserIds: string[] }) =>
      apiRequest(`/console/api/v1/operations/access-requests/${row.id}/reassign`, {
        method: "POST",
        body: { approver_user_ids: approverUserIds } satisfies JsonObject,
      }),
    onSuccess: () => {
      onActionSuccess(t("console.accessRequests.reassigned"));
    },
    onError: handleAccessRequestActionError,
  });
  const retryGrantMutation = useMutation({
    mutationFn: ({ row, reason }: { row: OperationRow; reason: string }) =>
      apiRequest(`/console/api/v1/operations/access-requests/${row.id}/retry-grant`, {
        method: "POST",
        body: { reason } satisfies JsonObject,
      }),
    onSuccess: () => {
      onActionSuccess(t("console.operations.retryGrantSuccess"));
    },
  });

  const openAccessRequestAction = (type: AccessRequestActionType, row: OperationRow) => {
    decisionMutation.reset();
    reassignMutation.reset();
    retryGrantMutation.reset();
    controls.setPendingAction({ type, row });
  };

  return { decisionMutation, reassignMutation, retryGrantMutation, openAccessRequestAction };
}

export type RevokeGrantControls = ReturnType<typeof useRevokeGrantMutation>;

export function useRevokeGrantMutation(controls: OperationPendingControls) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const invalidateAccessGrants = () =>
    queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-grants"] });

  const revokeGrantMutation = useMutation({
    mutationFn: ({ row, reason }: { row: AccessGrantRow; reason: string }) =>
      apiRequest("/console/api/v1/operations/emergency-revokes", {
        method: "POST",
        body: { user_id: row.user_id, app_key: row.app_key, reason } satisfies JsonObject,
      }),
    onSuccess: () => {
      controls.setPendingRevokeGrant(null);
      controls.setOperationNotice(null);
      toast.success(t("console.operations.revokeSuccess"));
      void invalidateAccessGrants();
    },
    onError: (error: Error) => {
      if (isActiveGrantNotFoundConflict(error)) {
        controls.setPendingRevokeGrant(null);
        controls.setOperationNotice({
          tone: "amber",
          title: t("console.operations.revokeConflict"),
          message: t("console.operations.revokeConflictDescription"),
        });
        toast.warning(t("console.operations.revokeConflict"));
        void invalidateAccessGrants();
        return;
      }
      // 权限来自组织授权: 授权本身没有变化, 不必刷新列表, 也不该当成一次失败留在弹窗里。
      if (isDepartmentSourcedGrantConflict(error)) {
        controls.setPendingRevokeGrant(null);
        controls.setOperationNotice(null);
        toast.warning(
          t("console.operations.revokeDepartmentConflict"),
          t("console.operations.revokeDepartmentConflictDescription"),
        );
      }
    },
  });

  const openRevokeGrant = (row: AccessGrantRow) => {
    revokeGrantMutation.reset();
    controls.setPendingRevokeGrant(row);
  };

  return { revokeGrantMutation, openRevokeGrant };
}

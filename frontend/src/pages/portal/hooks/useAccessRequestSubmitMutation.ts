import { useMutation } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiRequest } from "../../../lib/api";
import { queryClient } from "../../../lib/query";
import { buildAccessRequestPayload } from "./accessRequestPayload";
import type { AccessRequestFields, CatalogView } from "./accessRequestTypes";

export function useAccessRequestSubmitMutation(
  fields: AccessRequestFields,
  catalogView: CatalogView,
): UseMutationResult<unknown, Error, void, unknown> {
  const pendingSubmission = useRef<{
    payload: string;
    idempotencyKey: string;
    draftRevision: number;
  } | null>(null);
  const draftRevision = useRef(0);
  // 草稿每次编辑推进 revision; 提交成功时仅当 revision 未变才 reset, 避免清空用户新草稿。
  useEffect(() => {
    draftRevision.current += 1;
  }, [
    fields.appKey,
    fields.requestType,
    fields.baseGrantId,
    fields.baseGrantRevision,
    fields.authorizationGroupKeys,
    fields.selectedPermissionKeys,
    fields.selectedPermissionScopes,
    fields.selectedApproverUserIds,
    fields.grantType,
    fields.expiresAt,
    fields.reason,
  ]);
  return useMutation({
    mutationFn: () => {
      const payload = buildAccessRequestPayload(fields, catalogView);
      const serializedPayload = JSON.stringify(payload);
      if (pendingSubmission.current?.payload !== serializedPayload) {
        pendingSubmission.current = {
          payload: serializedPayload,
          idempotencyKey: crypto.randomUUID(),
          draftRevision: draftRevision.current,
        };
      }
      return apiRequest("/portal/api/v1/me/access-requests", {
        method: "POST",
        headers: { "Idempotency-Key": pendingSubmission.current.idempotencyKey },
        body: payload,
      });
    },
    onSuccess: () => {
      const submittedRevision = pendingSubmission.current?.draftRevision;
      pendingSubmission.current = null;
      // 仅当提交期间草稿未变时清空目标与理由, 避免旧成功响应抹掉新编辑。
      if (submittedRevision === draftRevision.current) {
        fields.setAuthorizationGroupKeys([]);
        fields.setSelectedPermissionKeys([]);
        fields.setSelectedPermissionScopes({});
        fields.setApproverSelectionWasEdited(false);
        fields.setReason("");
      }
      void queryClient.invalidateQueries({ queryKey: ["portal", "requests"] });
    },
  });
}

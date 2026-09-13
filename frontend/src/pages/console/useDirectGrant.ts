import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { userOptionName } from "../../components/UserCombobox";
import type { UserOption } from "../../components/UserCombobox";
import { useToast } from "../../components/ui/Toast";
import {
  EMPTY_GRANT_DRAFT,
  buildGrantSubmission,
  departmentSourcedGroupKeys,
  departmentSourcedPermissionKeys,
  grantCatalogApp,
  grantDraftErrors,
  grantDraftExcludingLockedKeys,
  grantDraftFromCurrentGrant,
  grantDraftIsValid,
  grantDraftWithoutGrantee,
  useCurrentGrant,
  useGrantCatalog,
} from "../../features/grantForm";
import type { GrantDraft, GrantSubmission } from "../../features/grantForm";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/messages";
import { apiRequest } from "../../lib/api";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { buildCatalogView } from "../portal/hooks/accessRequestCatalog";
import { detailErrorMessages } from "./DirectGrantErrors";

interface DirectGrantRequest {
  payload: GrantSubmission & { user_id: string };
  granteeLabel: string;
  appLabel: string;
}

export function useDirectGrant() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const catalogQuery = useGrantCatalog();
  const [userId, setUserId] = useState("");
  const [grantee, setGrantee] = useState<UserOption | null>(null);
  const [draft, setDraft] = useState<GrantDraft>(EMPTY_GRANT_DRAFT);
  const [draftErrorKeys, setDraftErrorKeys] = useState<MessageKey[]>([]);
  const currentGrantQuery = useCurrentGrant(userId, draft.appKey);
  /**
   * 已经结清回填的那一对"被授权人 + 应用"。
   *
   * 回填对每一对只做一次: 管理员在响应到达之前就动了表单, 这一对立即结清, 迟到的响应不能盖掉编辑。
   * 换人、换应用或清空之后这一对重新开张(见下面的效果), 否则再选回同一对时表单会一直空着。
   */
  const settledPairRef = useRef("");
  const lastPairRef = useRef("");
  const reportedErrorPairRef = useRef("");
  const grantPairKey = userId !== "" && draft.appKey !== "" ? `${userId}\u0000${draft.appKey}` : "";
  const currentGrant = currentGrantQuery.isSuccess ? (currentGrantQuery.data ?? null) : null;
  const lockedAuthorizationGroupKeys = currentGrant ? departmentSourcedGroupKeys(currentGrant) : [];
  const lockedPermissionKeys = currentGrant ? departmentSourcedPermissionKeys(currentGrant) : [];

  useDirectGrantPrefill({
    catalogQuery,
    currentGrantQuery,
    grantPairKey,
    lastPairRef,
    settledPairRef,
    setDraft,
  });

  useEffect(() => {
    // 读不到现状就把失败说出来, 让表单停在空白态: 静默留白会让管理员以为这个人还没有权限。
    if (grantPairKey === "" || !currentGrantQuery.error || reportedErrorPairRef.current === grantPairKey) {
      return;
    }
    reportedErrorPairRef.current = grantPairKey;
    toast.error(t("directGrant.currentGrantFailed"), currentGrantQuery.error.message);
  }, [grantPairKey, currentGrantQuery.error, toast, t]);

  const grantMutation = useMutation<unknown, Error, DirectGrantRequest>({
    mutationFn: (request) =>
      apiRequest<unknown>("/console/api/v1/direct-grants", { method: "POST", body: request.payload }),
    onSuccess: (_data, request) => {
      toast.success(t("directGrant.succeeded", { name: request.granteeLabel, app: request.appLabel }));
      setDraftErrorKeys([]);
      // 被授权人保持选中: 连续给同一个人授权是最常见的操作。
      setDraft(EMPTY_GRANT_DRAFT);
      // 现状已经被这次授权改写: 连缓存一起丢掉并允许重新回填, 否则再选回同一个应用会回填过期的现状。
      settledPairRef.current = "";
      lastPairRef.current = "";
      queryClient.removeQueries({ queryKey: ["console", "current-grant"] });
      void queryClient.invalidateQueries({ queryKey: ["console", "operations", "access-grants"] });
    },
  });

  return {
    t,
    catalogQuery,
    userId,
    grantee,
    draft,
    draftErrorKeys,
    currentGrantQuery,
    currentGrant,
    lockedAuthorizationGroupKeys,
    lockedPermissionKeys,
    grantMutation,
    catalogErrorMessage: catalogQuery.error ? catalogQuery.error.message : "",
    canSubmit: Boolean(userId) && grantDraftIsValid(draft, catalogQuery.data),
    submitErrorMessages: detailErrorMessages(grantMutation.error),
    submit: () => {
      // 渲染时算出来的闸门会过期: 用户填完未来的到期时间后可以一直等到它走进过去, 那时按钮还亮着。
      // 这里重算一次, 拦下来就把原因显示出来, 而不是让 buildGrantSubmission 同步抛错却什么都不显示。
      const errors = grantDraftErrors(draft, catalogQuery.data);
      if (errors.length > 0) {
        setDraftErrorKeys(errors.map((error) => error.messageKey));
        return;
      }
      setDraftErrorKeys([]);
      grantMutation.mutate({
        payload: { user_id: userId, ...buildGrantSubmission(draft) },
        granteeLabel: userOptionName(grantee ?? undefined, userId),
        appLabel: formatAppDisplayName(grantCatalogApp(catalogQuery.data, draft.appKey)),
      });
    },
    changeGrantee: (nextUserId: string, nextOption: UserOption | null) => {
      setUserId(nextUserId);
      setGrantee(nextOption);
      // 目标与期限描述的是上一个人的现状, 换人后一条都不成立。
      setDraft(grantDraftWithoutGrantee(draft));
      setDraftErrorKeys([]);
    },
    setGrantee,
    setDraft,
    setDraftErrorKeys,
    settledPairRef,
    grantPairKey,
    reset: () => {
      setUserId("");
      setGrantee(null);
      setDraft(EMPTY_GRANT_DRAFT);
      setDraftErrorKeys([]);
      settledPairRef.current = "";
      lastPairRef.current = "";
      reportedErrorPairRef.current = "";
      grantMutation.reset();
    },
  };
}

function useDirectGrantPrefill({
  catalogQuery,
  currentGrantQuery,
  grantPairKey,
  lastPairRef,
  settledPairRef,
  setDraft,
}: {
  catalogQuery: ReturnType<typeof useGrantCatalog>;
  currentGrantQuery: ReturnType<typeof useCurrentGrant>;
  grantPairKey: string;
  lastPairRef: { current: string };
  settledPairRef: { current: string };
  setDraft: (updater: (current: GrantDraft) => GrantDraft) => void;
}) {
  useEffect(() => {
    if (lastPairRef.current !== grantPairKey) {
      // 换了人、换了应用或清空重来: 上一对的结论作废, 这一对重新等待回填。
      lastPairRef.current = grantPairKey;
      settledPairRef.current = "";
    }
    if (grantPairKey === "" || settledPairRef.current === grantPairKey || !currentGrantQuery.isSuccess) {
      return;
    }
    settledPairRef.current = grantPairKey;
    const grant = currentGrantQuery.data;
    if (grant) {
      setDraft((current) => {
        const next = grantDraftFromCurrentGrant(grant, current);
        // 锁定组覆盖的直接权限也要从草稿里摘掉, 否则提交会把组织授权再抄一份。
        return grantDraftExcludingLockedKeys(
          next,
          departmentSourcedGroupKeys(grant),
          departmentSourcedPermissionKeys(grant),
          buildCatalogView(catalogQuery.data, next.appKey, ""),
        );
      });
    }
  }, [grantPairKey, currentGrantQuery.isSuccess, currentGrantQuery.data, catalogQuery.data, lastPairRef, settledPairRef, setDraft]);
}

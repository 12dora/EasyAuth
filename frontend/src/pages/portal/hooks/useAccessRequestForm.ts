import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiRequest } from "../../../lib/api";
import { parsePortalGrantList } from "../portalListPayload";
import { parsePortalRequestCatalog } from "../requestCatalogContract";
import { buildAccessRequestActions } from "./accessRequestActions";
import { buildCatalogView } from "./accessRequestCatalog";
import { buildAccessRequestFormResult } from "./accessRequestFormResult";
import type { AccessRequestFormResult } from "./accessRequestTypes";
import {
  accessRequestCanSubmit,
  accessRequestExpiresAtError,
  accessRequestExpiresAtIsFuture,
  accessRequestSubmitGateMessageKey,
} from "./accessRequestValidation";
import { useAccessRequestFields } from "./useAccessRequestFields";
import {
  useDefaultApprovers,
  useDefaultSingleScopes,
  useGroupCoverageInvariant,
  useLifecycleGrantInvariant,
} from "./useAccessRequestInvariants";
import {
  useAccessRequestPrefillApplication,
  type AccessRequestPrefill,
} from "./useAccessRequestPrefill";
import { useAccessRequestSubmitMutation } from "./useAccessRequestSubmitMutation";

export interface UseAccessRequestFormOptions {
  /** 由路由 state 带来的预填; null 表示本次进入页面没有预填。 */
  prefill?: AccessRequestPrefill | null;
  onPrefillApplied?: () => void;
  /** 申请提交成功时的回调(页面用它弹 toast); hook 本身不生产用户可见文案。 */
  onSubmitted?: () => void;
}

export function useAccessRequestForm(currentUserId = "", options: UseAccessRequestFormOptions = {}): AccessRequestFormResult {
  const prefill = options.prefill ?? null;
  const fields = useAccessRequestFields(prefill?.requestType);
  const catalogQuery = useQuery({
    queryKey: ["portal", "request-catalog"],
    queryFn: async () => parsePortalRequestCatalog(await apiRequest<unknown>("/portal/api/v1/request-catalog")),
  });
  // 现有授权对每一种申请类型都是必需的: 选中应用时要按它判断这次申请是新增还是变更(后端对已有
  // 生效授权的应用拒绝新增申请), 生命周期申请还要用它当基础授权。
  const currentGrantsQuery = useQuery({
    queryKey: ["portal", "current-grants-selector"],
    queryFn: async () =>
      parsePortalGrantList(await apiRequest<unknown>("/portal/api/v1/me/grants?page=1&page_size=100")),
  });
  const catalogView = useMemo(
    () => buildCatalogView(catalogQuery.data, fields.appKey, currentUserId),
    [fields.appKey, catalogQuery.data, currentUserId],
  );
  useDefaultSingleScopes(fields.setSelectedPermissionScopes, catalogView);
  useGroupCoverageInvariant(fields, catalogView);
  useDefaultApprovers(fields, catalogView, currentUserId);
  const submitMutation = useAccessRequestSubmitMutation(fields, catalogView, options.onSubmitted);
  const currentGrants = currentGrantsQuery.data?.data ?? [];
  const selectedBaseGrant = currentGrants.find((grant) => String(grant.grant_id) === fields.baseGrantId);
  useLifecycleGrantInvariant(fields, selectedBaseGrant);
  const actions = buildAccessRequestActions(fields, catalogView, currentGrants, () => {
    fields.setGroupMaterializationNoticeKey("");
    submitMutation.mutate();
  });
  const prefillErrorMessageKey = useAccessRequestPrefillApplication({
    prefill,
    currentGrants,
    currentGrantsAreLoaded: currentGrantsQuery.isSuccess,
    changeBaseGrantId: actions.changeBaseGrantId,
    onApplied: options.onPrefillApplied,
  });
  const currentGrantsTruncated = Boolean(currentGrantsQuery.data && currentGrantsQuery.data.pagination.total_pages > 1);
  const catalogIsLoading = catalogQuery.isLoading || currentGrantsQuery.isLoading;
  // 只读一次时钟: canSubmit 与 expiresAtError 必须基于同一瞬间判断限时授权是否已过期,
  // 否则同一次 render 可能同时给出"可提交"和"已过期"。
  const grantTermIsFuture = accessRequestExpiresAtIsFuture(fields);

  const result = buildAccessRequestFormResult({
    fields,
    catalogView,
    currentGrants,
    selectedBaseGrant,
    catalogIsLoading,
    catalogError: catalogQuery.error ?? currentGrantsQuery.error,
    submitMutation,
    canSubmit: accessRequestCanSubmit({
      grantTermIsFuture,
      values: fields,
      catalogView,
      selectedBaseGrant,
      currentGrantsTruncated,
      isSubmitting: submitMutation.isPending,
      currentUserId,
    }),
    expiresAtError: accessRequestExpiresAtError(fields, grantTermIsFuture),
    actions,
    currentGrantsTruncated,
    prefillErrorMessageKey,
  });

  // 权限组落地是对用户上一次点击的即时反馈, 占用同一条提示位时优先于"当前应用没有直接权限"这类派生提示。
  // 但提交闸门的拦截原因更要紧: 闸门亮着时提交按钮是灰的, 提示位必须说清楚为什么, 不能被落地提示盖掉。
  // 提示键留在 fields 里不清, 闸门解除后它还会接着显示, 不会因为让位而丢掉。
  const submitGateMessageKey = accessRequestSubmitGateMessageKey(fields, catalogView, selectedBaseGrant);
  return fields.groupMaterializationNoticeKey && !submitGateMessageKey
    ? { ...result, noticeMessageKey: fields.groupMaterializationNoticeKey }
    : result;
}

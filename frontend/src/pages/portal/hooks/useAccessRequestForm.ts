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
}

export function useAccessRequestForm(currentUserId = "", options: UseAccessRequestFormOptions = {}): AccessRequestFormResult {
  const prefill = options.prefill ?? null;
  const fields = useAccessRequestFields(prefill?.requestType);
  const catalogQuery = useQuery({
    queryKey: ["portal", "request-catalog"],
    queryFn: async () => parsePortalRequestCatalog(await apiRequest<unknown>("/portal/api/v1/request-catalog")),
  });
  const currentGrantsQuery = useQuery({
    queryKey: ["portal", "current-grants-selector"],
    queryFn: async () =>
      parsePortalGrantList(await apiRequest<unknown>("/portal/api/v1/me/grants?page=1&page_size=100")),
    enabled: fields.requestType !== "grant",
  });
  const catalogView = useMemo(
    () => buildCatalogView(catalogQuery.data, fields.appKey, currentUserId),
    [fields.appKey, catalogQuery.data, currentUserId],
  );
  useDefaultSingleScopes(fields.setSelectedPermissionScopes, catalogView);
  useGroupCoverageInvariant(fields, catalogView);
  useDefaultApprovers(fields, catalogView, currentUserId);
  const submitMutation = useAccessRequestSubmitMutation(fields, catalogView);
  const currentGrants = currentGrantsQuery.data?.data ?? [];
  const selectedBaseGrant = currentGrants.find((grant) => String(grant.grant_id) === fields.baseGrantId);
  useLifecycleGrantInvariant(fields, selectedBaseGrant);
  const actions = buildAccessRequestActions(fields, catalogView, currentGrants, () => submitMutation.mutate());
  const prefillErrorMessageKey = useAccessRequestPrefillApplication({
    prefill,
    currentGrants,
    currentGrantsAreLoaded: currentGrantsQuery.isSuccess,
    changeBaseGrantId: actions.changeBaseGrantId,
    onApplied: options.onPrefillApplied,
  });
  const lifecycleSelectorActive = fields.requestType !== "grant";
  const currentGrantsTruncated = Boolean(currentGrantsQuery.data && currentGrantsQuery.data.pagination.total_pages > 1);
  const catalogIsLoading = catalogQuery.isLoading || (lifecycleSelectorActive && currentGrantsQuery.isLoading);
  // 只读一次时钟: canSubmit 与 expiresAtError 必须基于同一瞬间判断限时授权是否已过期,
  // 否则同一次 render 可能同时给出"可提交"和"已过期"。
  const grantTermIsFuture = accessRequestExpiresAtIsFuture(fields);

  return buildAccessRequestFormResult({
    fields,
    catalogView,
    currentGrants,
    catalogIsLoading,
    catalogError: catalogQuery.error ?? (lifecycleSelectorActive ? currentGrantsQuery.error : null),
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
}

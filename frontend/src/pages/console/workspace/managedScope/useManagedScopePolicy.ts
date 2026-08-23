import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import { invalidateAppDerivedQueries } from "../invalidateAppQueries";
import {
  payloadForManagedScopeSelection,
  selectionFromManagedScopePayload,
  validateManagedScopePolicyPayload,
  type ManagedScopeLoadState,
  type ManagedScopeSelection,
} from "./managedScopePolicyPayload";

/** 应用级 MANAGED_USERS 策略的读取/保存, 以及下拉选择与后端快照的同步。 */
export function useManagedScopePolicy(appKey: string) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [selection, setSelection] = useState<ManagedScopeSelection>("unconfigured");
  const queryKey = ["console", "app", appKey, "managed-scope-policy"];
  const policyQuery = useQuery({
    queryKey,
    queryFn: async () => validateManagedScopePolicyPayload(
      await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/managed-scope-policy`),
      t("console.managedScope.invalidResponse"),
    ),
    enabled: Boolean(appKey),
  });
  const saveMutation = useMutation({
    mutationFn: async () =>
      validateManagedScopePolicyPayload(
        await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/managed-scope-policy`, {
          method: "PATCH",
          body: { managed_scope_policy: payloadForManagedScopeSelection(selection) } satisfies JsonObject,
        }),
        t("console.managedScope.invalidResponse"),
      ),
    onSuccess: (payload) => {
      queryClient.setQueryData(queryKey, payload);
      invalidateAppDerivedQueries(queryClient, appKey);
    },
  });
  const policyQueryError = policyQuery.error ?? policyQuery.failureReason;
  const loadState: ManagedScopeLoadState = policyQuery.isFetching || policyQuery.isPending
    ? "loading"
    : policyQuery.isRefetchError || policyQueryError
      ? "error"
      : policyQuery.data?.managed_scope_policy
        ? "configured"
        : "unconfigured";

  useEffect(() => {
    if (!policyQuery.data) {
      return;
    }
    setSelection(selectionFromManagedScopePayload(policyQuery.data));
  }, [policyQuery.data]);

  return {
    selection,
    setSelection,
    policyQuery,
    policyQueryError,
    saveMutation,
    loadState,
    // 只有拿到权威快照(已配置/未配置)才允许保存, 加载中与失败态都禁用
    hasAuthoritativeSnapshot: loadState === "configured" || loadState === "unconfigured",
    teamBasedSelection: selection === "easyauth_team" || selection === "union",
    effectivePolicy: policyQuery.data?.effective_managed_scope_policy ?? null,
  };
}

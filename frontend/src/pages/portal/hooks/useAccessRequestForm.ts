import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiRequest } from "../../../lib/api";
import { parsePortalGrantList } from "../portalListPayload";
import { parsePortalRequestCatalog } from "../requestCatalogContract";
import { buildAccessRequestActions } from "./accessRequestActions";
import { buildCatalogView } from "./accessRequestCatalog";
import { buildAccessRequestFormResult } from "./accessRequestFormResult";
import type { AccessRequestFormResult } from "./accessRequestTypes";
import { accessRequestCanSubmit, accessRequestExpiresAtError } from "./accessRequestValidation";
import { useAccessRequestFields } from "./useAccessRequestFields";
import {
  useDefaultApprovers,
  useDefaultSingleScopes,
  useGroupCoverageInvariant,
  useLifecycleGrantInvariant,
} from "./useAccessRequestInvariants";
import { useAccessRequestSubmitMutation } from "./useAccessRequestSubmitMutation";

export function useAccessRequestForm(currentUserId = ""): AccessRequestFormResult {
  const fields = useAccessRequestFields();
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
  const lifecycleSelectorActive = fields.requestType !== "grant";
  const currentGrantsTruncated = Boolean(currentGrantsQuery.data && currentGrantsQuery.data.pagination.total_pages > 1);
  const catalogIsLoading = catalogQuery.isLoading || (lifecycleSelectorActive && currentGrantsQuery.isLoading);

  return buildAccessRequestFormResult({
    fields,
    catalogView,
    currentGrants,
    catalogIsLoading,
    catalogError: catalogQuery.error ?? (lifecycleSelectorActive ? currentGrantsQuery.error : null),
    submitMutation,
    canSubmit: accessRequestCanSubmit({
      values: fields,
      catalogView,
      selectedBaseGrant,
      currentGrantsTruncated,
      isSubmitting: submitMutation.isPending,
      currentUserId,
    }),
    expiresAtError: accessRequestExpiresAtError(fields),
    actions,
    currentGrantsTruncated,
  });
}

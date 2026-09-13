import { useQuery, type QueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest, itemsFromPayload } from "../../../../lib/api";
import type { JsonObject, ListPayload } from "../../../../lib/api";
import type { ConfigurationStatus } from "../../../../lib/domain";
import { useApiMutation } from "../../../../lib/query";
import { invalidateAppDerivedQueries } from "../invalidateAppQueries";
import type { MembershipCreatePayload, MembershipItem } from "./overviewModel";

/** 概览页的配置状态/成员两条查询与成员增改, 以及新建成员弹窗开合。 */
export function useOverviewData(appKey: string) {
  const [membershipDialogOpen, setMembershipDialogOpen] = useState(false);
  const membershipsQueryKey = ["console", "app", appKey, "memberships"];
  const statusQuery = useQuery({
    queryKey: ["console", "app", appKey, "configuration-status"],
    queryFn: () => apiRequest<ConfigurationStatus>(`/console/api/v1/apps/${appKey}/configuration-status`),
    enabled: Boolean(appKey),
  });
  const membershipsQuery = useQuery({
    queryKey: membershipsQueryKey,
    queryFn: () => apiRequest<ListPayload<MembershipItem>>(`/console/api/v1/apps/${appKey}/memberships`),
    enabled: Boolean(appKey),
  });
  const invalidateMemberships = (client: QueryClient) => {
    void client.invalidateQueries({ queryKey: membershipsQueryKey });
    invalidateAppDerivedQueries(client, appKey);
  };
  const createMembershipMutation = useApiMutation({
    mutationFn: (payload: MembershipCreatePayload) =>
      apiRequest(`/console/api/v1/apps/${appKey}/memberships`, {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    invalidate: invalidateMemberships,
    onSuccess: () => {
      setMembershipDialogOpen(false);
    },
  });
  const disableMembershipMutation = useApiMutation({
    mutationFn: (membershipId: number) =>
      apiRequest(`/console/api/v1/apps/${appKey}/memberships/${membershipId}`, {
        method: "PATCH",
        body: { is_active: false },
      }),
    invalidate: invalidateMemberships,
  });

  return {
    statusQuery,
    membershipsQuery,
    memberships: itemsFromPayload<MembershipItem>(membershipsQuery.data),
    createMembershipMutation,
    disableMembershipMutation,
    membershipDialogOpen,
    setMembershipDialogOpen,
  };
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { HandoverAction, HandoverGrantItemRow, HandoverTaskDetail } from "../../../lib/domain";
import { changedGrantSelections, mergeGrantSelection } from "./handoverWizardModel";

/** 离职向导「授权」段: 权限清单装载、勾选草稿与批量 PATCH。 */
export function useHandoverWizardGrants(task: HandoverTaskDetail, selectedApps: HandoverAction[]) {
  const queryClient = useQueryClient();
  const grantItemsQueryKey = useMemo(
    () => ["console", "handover-task", String(task.id), "grant-items"],
    [task.id],
  );
  const [grantSelection, setGrantSelection] = useState<Record<number, boolean>>({});

  const grantItemsQuery = useQuery({
    queryKey: grantItemsQueryKey,
    queryFn: () =>
      apiRequest<ListPayload<HandoverGrantItemRow>>(`/console/api/v1/lifecycle/handover-tasks/${task.id}/grant-items`),
    enabled: task.kind === "offboard",
  });
  const grantItems = useMemo(
    () => itemsFromPayload<HandoverGrantItemRow>(grantItemsQuery.data),
    [grantItemsQuery.data],
  );

  useEffect(() => {
    setGrantSelection((current) => mergeGrantSelection(current, grantItems));
  }, [grantItems]);

  const saveGrantsMutation = useMutation({
    mutationFn: async () => {
      const items = changedGrantSelections(grantItems, selectedApps, grantSelection);
      if (items.length === 0) {
        return;
      }
      await apiRequest(`/console/api/v1/lifecycle/handover-tasks/${task.id}/grant-items`, {
        method: "PATCH",
        body: { items } satisfies JsonObject,
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: grantItemsQueryKey }),
  });

  return {
    grantItems,
    grantSelection,
    toggleGrant: (id: number, checked: boolean) =>
      setGrantSelection((current) => ({ ...current, [id]: checked })),
    isLoading: grantItemsQuery.isLoading,
    error: grantItemsQuery.error,
    saveGrantsMutation,
  };
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { AppListPayload, AppSummary } from "../../lib/domain";
import type { AppCreateFormPayload } from "./ConsoleAppCreateDialog";

/** 应用列表的装载、快速新建、行内启停与删除。 */
export function useConsoleAppList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<AppSummary | null>(null);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 20 });

  const appsQuery = useQuery({
    queryKey: ["console", "apps", pagination.pageIndex, pagination.pageSize],
    queryFn: () =>
      apiRequest<AppListPayload>(`/console/api/v1/apps?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`),
  });
  const createMutation = useMutation({
    mutationFn: (payload: AppCreateFormPayload) =>
      apiRequest<AppListPayload>("/console/api/v1/apps", {
        method: "POST",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
      const appKey = payload.app?.app_key;
      if (appKey) {
        void navigate(`/console/apps/${appKey}`);
      }
    },
  });
  const updateStatusMutation = useMutation({
    mutationFn: ({ appKey, isActive }: { appKey: string; isActive: boolean }) =>
      apiRequest(`/console/api/v1/apps/${appKey}`, {
        method: "PATCH",
        body: { is_active: isActive },
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["console", "apps"] }),
  });
  const deleteMutation = useMutation({
    mutationFn: (app: AppSummary) =>
      apiRequest(`/console/api/v1/apps/${app.app_key}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
    },
  });

  const apps = itemsFromPayload<AppSummary>(appsQuery.data);

  return {
    appsQuery,
    apps,
    pageCount: appsQuery.data?.pagination?.total_pages ?? 1,
    totalItems: appsQuery.data?.pagination?.total_items ?? apps.length,
    pagination,
    setPagination,
    createDialogOpen,
    setCreateDialogOpen,
    deleteTarget,
    setDeleteTarget,
    createMutation,
    updateStatusMutation,
    deleteMutation,
  };
}

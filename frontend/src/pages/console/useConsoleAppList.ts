import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { serverTableQuery, useServerTable } from "../../components/antd/AppTable";
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
  // 表头筛选映射到后端支持的两个查询键; 其余列后端无法过滤, 因此列上也不给筛选。
  const serverTable = useServerTable<AppSummary>({
    defaultPageSize: 20,
    filterParams: { status: "status", owners: "owner_user_id" },
  });
  const appsSearch = serverTableQuery(serverTable.params);

  const appsQuery = useQuery({
    queryKey: ["console", "apps", appsSearch],
    queryFn: () => apiRequest<AppListPayload>(`/console/api/v1/apps?${appsSearch}`),
    // 翻页时保留上一页数据, 分页条的总数与页码不会先塌回 0 再跳回来。
    placeholderData: (previous) => previous,
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
  serverTable.setTotal(appsQuery.data?.pagination?.total_items);

  return {
    appsQuery,
    apps,
    tableProps: serverTable.tableProps,
    createDialogOpen,
    setCreateDialogOpen,
    deleteTarget,
    setDeleteTarget,
    createMutation,
    updateStatusMutation,
    deleteMutation,
  };
}

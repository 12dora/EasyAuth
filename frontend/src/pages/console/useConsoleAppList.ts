import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ORDERING_PARAM, orderingSerializer, serverTableQuery, useServerTable } from "../../components/antd/AppTable";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { AppListPayload, AppSummary } from "../../lib/domain";
import type { AppCreateFormPayload } from "./ConsoleAppCreateDialog";

/**
 * 列 key -> 后端 `ordering` 字段(GET /console/api/v1/apps 只认这四个)。
 * 应用列同时显示名称与 app_key, 排序按后端默认序的那一个(app_key);
 * owners / configuration_status 后端排不了, 因此列上也不给 sorter。
 */
const APP_ORDERING_FIELDS = {
  app: "app_key",
  status: "status",
  updated_at: "updated_at",
} as const;

/** 后端默认序是 app_key 升序; defaultSort 与它一致, 首屏表头就带排序指示器。 */
const APP_DEFAULT_SORT = { field: "app", order: "ascend" } as const;

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
    sortParam: ORDERING_PARAM,
    defaultSort: APP_DEFAULT_SORT,
    serializeSort: orderingSerializer(APP_ORDERING_FIELDS),
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
    // 表头筛选的真相在 useServerTable 里, 列必须用 serverColumn 受控回去:
    // 否则 antd 会拿当前页再跑一遍客户端 onFilter(placeholderData 保留的上一页会被筛空),
    // 表头的「已筛选」图标也会和实际请求参数对不上。
    filters: serverTable.query.filters,
    // 排序同理: 表头指示器要跟着 ordering 参数走, 列必须用 serverSortColumn 受控回去。
    sort: serverTable.query,
    createDialogOpen,
    setCreateDialogOpen,
    deleteTarget,
    setDeleteTarget,
    createMutation,
    updateStatusMutation,
    deleteMutation,
  };
}

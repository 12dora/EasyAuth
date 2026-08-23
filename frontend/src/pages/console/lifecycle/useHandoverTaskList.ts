import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { DEFAULT_TABLE_PAGE_SIZE } from "../../../components/ui/TablePagination";
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import type { HandoverTaskRow } from "../../../lib/domain";
import type { HandoverTaskFilterValues } from "./handoverTaskListModel";
import { handoverTaskListQuery } from "./handoverTaskListModel";

/** 交接单列表的过滤、分页与删除。 */
export function useHandoverTaskList() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<HandoverTaskFilterValues>({
    status: "",
    kind: "",
    assigneeState: "",
    blocked: "",
  });
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_TABLE_PAGE_SIZE });
  const [deleteTarget, setDeleteTarget] = useState<HandoverTaskRow | null>(null);

  const tasksQuery = useQuery({
    queryKey: [
      "console",
      "handover-tasks",
      filters.status,
      filters.kind,
      filters.assigneeState,
      filters.blocked,
      pagination.pageIndex,
      pagination.pageSize,
    ],
    queryFn: () =>
      apiRequest<ListPayload<HandoverTaskRow>>(
        `/console/api/v1/lifecycle/handover-tasks?${handoverTaskListQuery(filters, pagination)}`,
      ),
  });
  const deleteMutation = useMutation({
    mutationFn: (task: HandoverTaskRow) =>
      apiRequest(`/console/api/v1/lifecycle/handover-tasks/${task.id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "handover-tasks"] });
      setDeleteTarget(null);
      toast.success(t("handover.list.deleteSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("handover.list.deleteFailed"), error.message);
    },
  });

  return {
    tasksQuery,
    tasks: itemsFromPayload<HandoverTaskRow>(tasksQuery.data),
    pageCount: tasksQuery.data?.pagination?.total_pages ?? 0,
    totalItems: tasksQuery.data?.pagination?.total_items ?? 0,
    filters,
    // 换过滤条件必须回到第一页, 否则会带着旧页码请求。
    setFilter: (patch: Partial<HandoverTaskFilterValues>) => {
      setFilters((current) => ({ ...current, ...patch }));
      setPagination((current) => ({ ...current, pageIndex: 0 }));
    },
    pagination,
    setPagination,
    deleteTarget,
    setDeleteTarget,
    deleteMutation,
  };
}

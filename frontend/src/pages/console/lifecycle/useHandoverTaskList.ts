import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { serverTableQuery, useServerTable } from "../../../components/antd/AppTable";
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import type { HandoverTaskRow } from "../../../lib/domain";

/** 交接单列表的过滤、分页与删除。 */
export function useHandoverTaskList() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [deleteTarget, setDeleteTarget] = useState<HandoverTaskRow | null>(null);
  // 四个后端过滤键全部来自表头筛选; 未选中的键不进查询串, 与后端"不传即不过滤"一致。
  const serverTable = useServerTable<HandoverTaskRow>({
    filterParams: {
      status: "status",
      kind: "kind",
      assignee_state: "assignee_state",
      blocked: "blocked",
    },
  });
  const tasksSearch = serverTableQuery(serverTable.params);

  const tasksQuery = useQuery({
    queryKey: ["console", "handover-tasks", tasksSearch],
    queryFn: () => apiRequest<ListPayload<HandoverTaskRow>>(`/console/api/v1/lifecycle/handover-tasks?${tasksSearch}`),
    placeholderData: (previous) => previous,
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

  const tasks = itemsFromPayload<HandoverTaskRow>(tasksQuery.data);
  serverTable.setTotal(tasksQuery.data?.pagination?.total_items);

  return {
    tasksQuery,
    tasks,
    tableProps: serverTable.tableProps,
    deleteTarget,
    setDeleteTarget,
    deleteMutation,
  };
}

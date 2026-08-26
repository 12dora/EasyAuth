import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
} from "../../../components/antd/AppTable";
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import type { HandoverTaskRow } from "../../../lib/domain";

/**
 * 列 key -> 后端 `ordering` 字段(GET /console/api/v1/lifecycle/handover-tasks 只认这四个)。
 * 负责人(assignee_state)与阻塞(blocked)两列只能筛不能排。
 */
const HANDOVER_ORDERING_FIELDS = {
  subject: "subject",
  kind: "kind",
  status: "status",
  created_at: "created_at",
} as const;

/** 后端默认序是 -created_at; defaultSort 与它一致, 首屏表头就带排序指示器。 */
const HANDOVER_DEFAULT_SORT = { field: "created_at", order: "descend" } as const;

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
    sortParam: ORDERING_PARAM,
    defaultSort: HANDOVER_DEFAULT_SORT,
    serializeSort: orderingSerializer(HANDOVER_ORDERING_FIELDS),
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
    // 表头筛选的真相在 useServerTable 里, 列必须用 serverColumn 受控回去:
    // 否则 antd 会拿当前页再跑一遍客户端 onFilter(placeholderData 保留的上一页会被筛空),
    // 表头的「已筛选」图标也会和实际请求参数对不上。
    filters: serverTable.query.filters,
    // 排序同理: 表头指示器要跟着 ordering 参数走, 列必须用 serverSortColumn 受控回去。
    sort: serverTable.query,
    deleteTarget,
    setDeleteTarget,
    deleteMutation,
  };
}

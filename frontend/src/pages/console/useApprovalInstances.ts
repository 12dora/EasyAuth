import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import {
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
} from "../../components/antd/AppTable";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { JsonValue, ListPayload } from "../../lib/api";
import { parseApprovalInstanceRow, type ApprovalInstanceRow } from "../../lib/domain";

export const INSTANCES_QUERY_PREFIX = ["console", "operations", "approval-instances"];
const DEFAULT_PAGE_SIZE = 20;
const LIST_ENDPOINT = "/console/api/v1/operations/approval-instances";

/**
 * 列 key -> 后端 `ordering` 字段。
 * 模板列的 key 是 template_key, 后端公开的排序字段名叫 template;
 * 发起人列的 key 是 originator_user_id, 后端字段叫 originator。
 */
const INSTANCE_ORDERING_FIELDS = {
  app_key: "app_key",
  template_key: "template",
  biz_key: "biz_key",
  originator_user_id: "originator",
  status: "status",
  dingtalk_process_instance_id: "dingtalk_process_instance_id",
  delivery: "delivery",
  created_at: "created_at",
} as const;

interface RedeliverPayload {
  approval_instance: JsonValue;
}

/** 审批实例列表的过滤、分页与逐行补投。 */
export function useApprovalInstances() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [redeliveringInstanceIds, setRedeliveringInstanceIds] = useState<ReadonlySet<string>>(new Set());
  const redeliveringInstanceIdsRef = useRef(new Set<string>());

  // 表头筛选、分页、「筛选后回第 1 页」全部交给 useServerTable;
  // 后端只支持 status 与 app_key 两个过滤参数。
  const serverTable = useServerTable<ApprovalInstanceRow>({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    filterParams: { status: "status", app_key: "app_key" },
    sortParam: ORDERING_PARAM,
    serializeSort: orderingSerializer(INSTANCE_ORDERING_FIELDS),
  });
  const queryString = serverTableQuery(serverTable.params);

  const query = useQuery({
    queryKey: [...INSTANCES_QUERY_PREFIX, queryString],
    queryFn: async ({ signal }) => {
      const payload = await apiRequest<ListPayload<JsonValue>>(`${LIST_ENDPOINT}?${queryString}`, { signal });
      return {
        ...payload,
        data: itemsFromPayload<JsonValue>(payload).map(parseApprovalInstanceRow),
      };
    },
  });
  const redeliverMutation = useMutation({
    mutationFn: (row: ApprovalInstanceRow) =>
      apiRequest<RedeliverPayload>(`${LIST_ENDPOINT}/${row.instance_id}/redeliver`, {
        method: "POST",
        body: {},
      }),
    onSuccess: async (payload) => {
      const instance = parseApprovalInstanceRow(payload.approval_instance);
      await queryClient.cancelQueries({ queryKey: INSTANCES_QUERY_PREFIX });
      queryClient.setQueriesData<ListPayload<ApprovalInstanceRow>>(
        { queryKey: INSTANCES_QUERY_PREFIX },
        (current) =>
          current?.data
            ? {
                ...current,
                data: current.data.map((row) =>
                  row.instance_id === instance.instance_id ? instance : row,
                ),
              }
            : current,
      );
      toast.success(t("approvalInstances.redelivered"));
      void queryClient.invalidateQueries({ queryKey: INSTANCES_QUERY_PREFIX });
    },
    onError: (error: Error) => {
      toast.error(t("approvalInstances.redeliverFailed"), error.message);
    },
    onSettled: (_data, _error, row) => {
      redeliveringInstanceIdsRef.current.delete(row.instance_id);
      setRedeliveringInstanceIds(new Set(redeliveringInstanceIdsRef.current));
    },
  });

  const rows = itemsFromPayload<ApprovalInstanceRow>(query.data);
  // 总条数只有请求回来后才知道, 因此拿到响应再回填(setTotal 内部做等值短路)。
  serverTable.setTotal(query.data?.pagination?.total_items);

  return {
    query,
    rows,
    tableProps: serverTable.tableProps,
    // 表头筛选的真相在 useServerTable 里, 列要用 serverColumn 受控回去。
    filters: serverTable.query.filters,
    // 排序同理: 表头指示器要跟着 ordering 参数走, 列要用 serverSortColumn 受控回去。
    sort: serverTable.query,
    isRedelivering: (row: ApprovalInstanceRow) => redeliveringInstanceIds.has(row.instance_id),
    redeliver: (row: ApprovalInstanceRow) => {
      if (redeliveringInstanceIdsRef.current.has(row.instance_id)) {
        return;
      }
      redeliveringInstanceIdsRef.current.add(row.instance_id);
      setRedeliveringInstanceIds(new Set(redeliveringInstanceIdsRef.current));
      redeliverMutation.mutate(row);
    },
  };
}

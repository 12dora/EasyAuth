import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { ListPayload } from "../../lib/api";
import type { ApprovalInstanceRow } from "../../lib/domain";

export const INSTANCES_QUERY_PREFIX = ["console", "operations", "approval-instances"];
const DEFAULT_PAGE_SIZE = 20;

interface RedeliverPayload {
  approval_instance: ApprovalInstanceRow;
}

/** 审批实例列表的过滤、分页与逐行补投。 */
export function useApprovalInstances() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState("");
  const [appKeyInput, setAppKeyInput] = useState("");
  const [appKeyFilter, setAppKeyFilter] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const [redeliveringInstanceIds, setRedeliveringInstanceIds] = useState<ReadonlySet<string>>(new Set());
  const redeliveringInstanceIdsRef = useRef(new Set<string>());

  // app_key 过滤输入去抖后生效, 避免每次按键都打后端。
  useEffect(() => {
    const timer = window.setTimeout(() => setAppKeyFilter(appKeyInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [appKeyInput]);

  // 过滤条件变化时回到第一页, 避免带着旧页码请求。
  useEffect(() => {
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  }, [statusFilter, appKeyFilter]);

  const query = useQuery({
    queryKey: [...INSTANCES_QUERY_PREFIX, statusFilter, appKeyFilter, pagination.pageIndex, pagination.pageSize],
    queryFn: ({ signal }) =>
      apiRequest<ListPayload<ApprovalInstanceRow>>(
        `/console/api/v1/operations/approval-instances?status=${encodeURIComponent(statusFilter)}&app_key=${encodeURIComponent(appKeyFilter)}&page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`,
        { signal },
      ),
  });
  const redeliverMutation = useMutation({
    mutationFn: (row: ApprovalInstanceRow) =>
      apiRequest<RedeliverPayload>(`/console/api/v1/operations/approval-instances/${row.instance_id}/redeliver`, {
        method: "POST",
        body: {},
      }),
    onSuccess: async (payload) => {
      await queryClient.cancelQueries({ queryKey: INSTANCES_QUERY_PREFIX });
      queryClient.setQueriesData<ListPayload<ApprovalInstanceRow>>(
        { queryKey: INSTANCES_QUERY_PREFIX },
        (current) =>
          current?.data
            ? {
                ...current,
                data: current.data.map((row) =>
                  row.instance_id === payload.approval_instance.instance_id ? payload.approval_instance : row,
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

  return {
    query,
    rows,
    pageCount: query.data?.pagination?.total_pages ?? 1,
    totalItems: query.data?.pagination?.total_items ?? rows.length,
    statusFilter,
    setStatusFilter,
    appKeyInput,
    setAppKeyInput,
    pagination,
    setPagination,
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

import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { HandoverTaskPayload, PersonRow } from "../../../lib/domain";
import { DEFAULT_PAGE_SIZE, PEOPLE_QUERY_PREFIX, type HandoverStartTarget } from "./consolePeopleModel";

/** 人员列表的过滤、分页与发起交接单。 */
export function useConsolePeopleList() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const [startTarget, setStartTarget] = useState<HandoverStartTarget | null>(null);

  // 搜索输入去抖后生效, 避免每次按键都打后端。
  useEffect(() => {
    const timer = window.setTimeout(() => setSearchFilter(searchInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  // 过滤条件变化时回到第一页, 避免带着旧页码请求。
  useEffect(() => {
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  }, [statusFilter, searchFilter]);

  const peopleQuery = useQuery({
    queryKey: [...PEOPLE_QUERY_PREFIX, statusFilter, searchFilter, pagination.pageIndex, pagination.pageSize],
    queryFn: () =>
      apiRequest<ListPayload<PersonRow>>(
        `/console/api/v1/users?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}&status=${encodeURIComponent(statusFilter)}&q=${encodeURIComponent(searchFilter)}`,
      ),
  });
  const createTaskMutation = useMutation({
    mutationFn: ({ kind, person, reason }: HandoverStartTarget & { reason: string }) =>
      apiRequest<HandoverTaskPayload>("/console/api/v1/lifecycle/handover-tasks", {
        method: "POST",
        body: { kind, user_id: person.user_id, reason } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      setStartTarget(null);
      const taskId = payload.handover_task?.id;
      if (taskId) {
        void navigate(`/console/lifecycle/handover-tasks/${taskId}`);
      }
    },
  });

  const people = itemsFromPayload<PersonRow>(peopleQuery.data);

  return {
    peopleQuery,
    people,
    pageCount: peopleQuery.data?.pagination?.total_pages ?? 1,
    totalItems: peopleQuery.data?.pagination?.total_items ?? people.length,
    statusFilter,
    setStatusFilter,
    searchInput,
    setSearchInput,
    pagination,
    setPagination,
    startTarget,
    setStartTarget,
    createTaskMutation,
    openHandover: (taskId: number) => void navigate(`/console/lifecycle/handover-tasks/${taskId}`),
    startHandover: (target: HandoverStartTarget) => {
      createTaskMutation.reset();
      setStartTarget(target);
    },
  };
}

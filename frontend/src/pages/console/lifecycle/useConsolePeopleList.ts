import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
} from "../../../components/antd/AppTable";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { HandoverTaskPayload, PersonRow } from "../../../lib/domain";
import { DEFAULT_PAGE_SIZE, PEOPLE_QUERY_PREFIX, type HandoverStartTarget } from "./consolePeopleModel";

/**
 * 列 key -> 后端 `ordering` 字段(GET /console/api/v1/users 只认这四个)。
 * 姓名列的 key 就是 name, 与后端字段同名。
 */
const PEOPLE_ORDERING_FIELDS = {
  name: "name",
  department: "department",
  email: "email",
  status: "status",
} as const;

/** 人员列表的过滤、分页、发起交接单与管理员权限配置。 */
export function useConsolePeopleList() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [searchFilter, setSearchFilter] = useState("");
  const [startTarget, setStartTarget] = useState<HandoverStartTarget | null>(null);
  const [permissionTarget, setPermissionTarget] = useState<PersonRow | null>(null);
  // status 走表头筛选; q 是真正的跨列搜索, 留在工具栏。
  const serverTable = useServerTable<PersonRow>({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    filterParams: { status: "status" },
    sortParam: ORDERING_PARAM,
    serializeSort: orderingSerializer(PEOPLE_ORDERING_FIELDS),
  });
  const { setPage } = serverTable;

  // 搜索输入去抖后生效, 避免每次按键都打后端。
  useEffect(() => {
    const timer = window.setTimeout(() => setSearchFilter(searchInput.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  // 搜索词变化时回到第一页, 避免带着旧页码请求(表头筛选由 useServerTable 自己回位)。
  useEffect(() => {
    setPage(1);
  }, [searchFilter, setPage]);

  const peopleSearch = serverTableQuery(serverTable.params, { q: searchFilter });
  const peopleQuery = useQuery({
    queryKey: [...PEOPLE_QUERY_PREFIX, peopleSearch],
    queryFn: () => apiRequest<ListPayload<PersonRow>>(`/console/api/v1/users?${peopleSearch}`),
    placeholderData: (previous) => previous,
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
  const updateConsoleAdminMutation = useMutation({
    mutationFn: ({ person, isConsoleAdmin }: { person: PersonRow; isConsoleAdmin: boolean }) =>
      apiRequest<{ user: PersonRow }>(`/console/api/v1/users/${encodeURIComponent(person.user_id)}/console-admin`, {
        method: "PUT",
        body: { is_console_admin: isConsoleAdmin } satisfies JsonObject,
      }),
    // 不拿响应里的 user 就地改写当前页: 列表的真相是重新拉取的那一页,
    // 后端拒绝(如取消自己的管理员权限)时弹窗要留在原地显示 error.message。
    onSuccess: () => {
      setPermissionTarget(null);
      void queryClient.invalidateQueries({ queryKey: PEOPLE_QUERY_PREFIX });
    },
  });

  const people = itemsFromPayload<PersonRow>(peopleQuery.data);
  serverTable.setTotal(peopleQuery.data?.pagination?.total_items);

  return {
    peopleQuery,
    people,
    tableProps: serverTable.tableProps,
    // 表头筛选的真相在 useServerTable 里, 列必须用 serverColumn 受控回去:
    // 否则 antd 会拿当前页再跑一遍客户端 onFilter(placeholderData 保留的上一页会被筛空),
    // 表头的「已筛选」图标也会和实际请求参数对不上。
    filters: serverTable.query.filters,
    // 排序同理: 表头指示器要跟着 ordering 参数走, 列必须用 serverSortColumn 受控回去。
    sort: serverTable.query,
    searchInput,
    setSearchInput,
    startTarget,
    setStartTarget,
    createTaskMutation,
    permissionTarget,
    setPermissionTarget,
    updateConsoleAdminMutation,
    openHandover: (taskId: number) => void navigate(`/console/lifecycle/handover-tasks/${taskId}`),
    startHandover: (target: HandoverStartTarget) => {
      createTaskMutation.reset();
      setStartTarget(target);
    },
    // reset 掉上一次的错误, 否则重开弹窗会带着旧的后端报错。
    openPermissions: (person: PersonRow) => {
      updateConsoleAdminMutation.reset();
      setPermissionTarget(person);
    },
  };
}

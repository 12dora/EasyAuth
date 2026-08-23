export const TASK_STATUSES = ["pending", "in_progress", "completed", "cancelled"] as const;
export const TASK_KINDS = ["offboard", "transfer", "pre_offboard", "reassign"] as const;
export const ASSIGNEE_STATES = ["manager", "subject", "superuser_pool"] as const;

export interface HandoverTaskFilterValues {
  status: string;
  kind: string;
  assigneeState: string;
  blocked: string;
}

/** assignee_state / blocked 只有选中时才进查询串, 保持与后端"不传即不过滤"的口径一致。 */
export function handoverTaskListQuery(
  filters: HandoverTaskFilterValues,
  pagination: { pageIndex: number; pageSize: number },
): URLSearchParams {
  const params = new URLSearchParams({
    status: filters.status,
    kind: filters.kind,
    page: String(pagination.pageIndex + 1),
    page_size: String(pagination.pageSize),
  });
  if (filters.assigneeState) {
    params.set("assignee_state", filters.assigneeState);
  }
  if (filters.blocked) {
    params.set("blocked", filters.blocked);
  }
  return params;
}

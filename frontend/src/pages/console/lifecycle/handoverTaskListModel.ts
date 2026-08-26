/** 表头枚举筛选的取值域; 与后端 status / kind / assignee_state 的枚举一一对应。 */
export const TASK_STATUSES = ["pending", "in_progress", "completed", "cancelled"] as const;
export const TASK_KINDS = ["offboard", "transfer", "pre_offboard", "reassign"] as const;
export const ASSIGNEE_STATES = ["manager", "subject", "superuser_pool"] as const;

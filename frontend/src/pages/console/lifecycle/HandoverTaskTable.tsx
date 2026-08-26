import { ArrowRight } from "lucide-react";
import { useMemo } from "react";

import { AppTable, enumFilter, type ColumnsType, type UseServerTableResult } from "../../../components/antd/AppTable";
import {
  RowActionButton,
  RowActionLink,
  actionsColumn,
  dateTimeColumn,
  serverColumn,
  statusColumn,
  textColumn,
  userColumn,
} from "../../../components/antd/columns";
import { Badge } from "../../../components/Badge";
import { daysLeftTone } from "../../../features/handover/surface";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverTaskRow } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";
import { ASSIGNEE_STATES, TASK_KINDS, TASK_STATUSES } from "./handoverTaskListModel";
import {
  handoverAssigneeStateLabel,
  handoverKindLabel,
  handoverTaskStatusLabel,
  handoverTaskStatusTone,
} from "./lifecycleLabels";

export interface HandoverTaskRowActions {
  onOpen: (taskId: number) => void;
  onDelete: (task: HandoverTaskRow) => void;
}

export function HandoverTaskTable({
  tasks,
  isLoading,
  tableProps,
  filters,
  actions,
}: {
  tasks: HandoverTaskRow[];
  isLoading: boolean;
  tableProps: UseServerTableResult<HandoverTaskRow>["tableProps"];
  /** 列 key -> 已选筛选值, 来自 useServerTable 的查询状态(四个键全在后端筛)。 */
  filters: Record<string, string[]>;
  actions: HandoverTaskRowActions;
}) {
  const { t } = useI18n();
  const columns = useMemo(() => taskColumns(t, filters, actions), [actions, filters, t]);

  return (
    <AppTable<HandoverTaskRow>
      {...tableProps}
      columns={columns}
      dataSource={tasks}
      emptyDescription={t("handover.list.empty.description")}
      emptyTitle={t("handover.list.empty.title")}
      loading={isLoading}
      minWidth={1180}
      rowKey="id"
    />
  );
}

/**
 * 四个后端过滤键(status / kind / assignee_state / blocked)各自挂在对应列的表头上,
 * 因此列表页不再有表格外的过滤条; 负责人与阻塞两列就是为了承载后两个筛选而存在。
 *
 * 四列一律过 `serverColumn`: 筛选真的发生在后端, 列上再留一份客户端 onFilter 会把
 * 当前页(翻页时还是 placeholderData 留下的上一页)按同一个值再筛一遍 ——
 * 负责人列显示的是人名、阻塞列显示的是计数, 都和筛选值对不上, 整页会被筛空。
 * serverColumn 默认 multiple: false, 与后端每个键只接受一个值一致。
 */
function taskColumns(
  t: Translator,
  filters: Record<string, string[]>,
  actions: HandoverTaskRowActions,
): ColumnsType<HandoverTaskRow> {
  return [
    userColumn<HandoverTaskRow>({
      key: "subject",
      title: t("handover.list.column.subject"),
      getName: (task) => task.subject.name || task.subject.user_id,
      getUserId: (task) => task.subject.email ?? "",
    }),
    serverColumn(
      {
        key: "kind",
        title: t("handover.list.column.kind"),
        width: 180,
        render: (_value: unknown, task: HandoverTaskRow) => (
          <div className="flex flex-wrap items-center gap-1">
            <span>{handoverKindLabel(t, task.kind)}</span>
            {task.escalation?.days_left != null ? (
              <Badge tone={daysLeftTone(task.escalation.days_left)}>{`${task.escalation.days_left}d`}</Badge>
            ) : null}
          </div>
        ),
        ...enumFilter<HandoverTaskRow>(
          "kind",
          TASK_KINDS.map((kind) => ({ value: kind, label: handoverKindLabel(t, kind) })),
        ),
      },
      filters.kind,
    ),
    serverColumn(
      statusColumn<HandoverTaskRow>({
        key: "status",
        title: t("common.status"),
        options: TASK_STATUSES.map((status) => ({
          value: status,
          label: handoverTaskStatusLabel(t, status),
          tone: handoverTaskStatusTone(status),
        })),
        width: 130,
      }),
      filters.status,
    ),
    serverColumn(
      {
        ...textColumn<HandoverTaskRow>({
          key: "assignee_state",
          title: t("handover.console.column.assignee"),
          getValue: (task) =>
            task.assignee?.name || task.assignee?.user_id || handoverAssigneeStateLabel(t, task.assignee_state),
          width: 160,
        }),
        ...enumFilter<HandoverTaskRow>(
          "assignee_state",
          ASSIGNEE_STATES.map((state) => ({ value: state, label: handoverAssigneeStateLabel(t, state) })),
        ),
      },
      filters.assignee_state,
    ),
    serverColumn(
      {
        key: "blocked",
        title: t("handover.console.column.blocked"),
        width: 130,
        render: (_value: unknown, task: HandoverTaskRow) =>
          task.blocked_app_count > 0 ? <Badge tone="signal">{task.blocked_app_count}</Badge> : "-",
        ...enumFilter<HandoverTaskRow>(
          "blocked",
          [
            { value: "true", label: t("handover.console.filter.blockedYes") },
            { value: "false", label: t("handover.console.filter.blockedNo") },
          ],
          { getValue: (task) => (task.blocked_app_count > 0 ? "true" : "false") },
        ),
      },
      filters.blocked,
    ),
    dateTimeColumn<HandoverTaskRow>({
      key: "created_at",
      title: t("handover.list.column.createdAt"),
      sorter: false,
    }),
    actionsColumn<HandoverTaskRow>({
      render: (task) => (
        <>
          <RowActionLink
            href={`/console/lifecycle/handover-tasks/${task.id}`}
            icon={<ArrowRight size={15} />}
            onClick={(event) => {
              event.preventDefault();
              actions.onOpen(task.id);
            }}
          >
            {t("handover.continue")}
          </RowActionLink>
          {task.allowed_actions?.includes("delete") ? (
            <RowActionButton type="button" variant="ghost-danger" onClick={() => actions.onDelete(task)}>
              {t("common.delete")}
            </RowActionButton>
          ) : null}
        </>
      ),
    }),
  ];
}

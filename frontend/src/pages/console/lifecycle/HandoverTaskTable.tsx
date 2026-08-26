import { ArrowRight } from "lucide-react";
import { useMemo } from "react";

import { AppTable, enumFilter, type ColumnsType, type UseServerTableResult } from "../../../components/antd/AppTable";
import { actionsColumn, dateTimeColumn, statusColumn, textColumn, userColumn } from "../../../components/antd/columns";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
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
  actions,
}: {
  tasks: HandoverTaskRow[];
  isLoading: boolean;
  tableProps: UseServerTableResult<HandoverTaskRow>["tableProps"];
  actions: HandoverTaskRowActions;
}) {
  const { t } = useI18n();
  const columns = useMemo(() => taskColumns(t, actions), [actions, t]);

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
 * 后端每个键只接受一个值, 因此这些表头筛选统一 filterMultiple: false。
 *
 * 四个后端过滤键(status / kind / assignee_state / blocked)各自挂在对应列的表头上,
 * 因此列表页不再有表格外的过滤条; 负责人与阻塞两列就是为了承载后两个筛选而存在。
 */
function taskColumns(t: Translator, actions: HandoverTaskRowActions): ColumnsType<HandoverTaskRow> {
  return [
    userColumn<HandoverTaskRow>({
      key: "subject",
      title: t("handover.list.column.subject"),
      getName: (task) => task.subject.name || task.subject.user_id,
      getUserId: (task) => task.subject.email ?? "",
    }),
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
      filterMultiple: false,
    },
    {
      ...statusColumn<HandoverTaskRow>({
        key: "status",
        title: t("common.status"),
        options: TASK_STATUSES.map((status) => ({
          value: status,
          label: handoverTaskStatusLabel(t, status),
          tone: handoverTaskStatusTone(status),
        })),
        width: 130,
      }),
      filterMultiple: false,
    },
    {
      ...textColumn<HandoverTaskRow>({
        key: "assignee_state",
        title: t("handover.console.column.assignee"),
        getValue: (task) => task.assignee?.name || task.assignee?.user_id || handoverAssigneeStateLabel(t, task.assignee_state),
        width: 160,
      }),
      ...enumFilter<HandoverTaskRow>(
        "assignee_state",
        ASSIGNEE_STATES.map((state) => ({ value: state, label: handoverAssigneeStateLabel(t, state) })),
      ),
      filterMultiple: false,
    },
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
      filterMultiple: false,
    },
    dateTimeColumn<HandoverTaskRow>({
      key: "created_at",
      title: t("handover.list.column.createdAt"),
      sorter: false,
    }),
    actionsColumn<HandoverTaskRow>({
      render: (task) => (
        <>
          <ButtonLink
            href={`/console/lifecycle/handover-tasks/${task.id}`}
            icon={<ArrowRight size={15} />}
            size="sm"
            variant="ghost"
            onClick={(event) => {
              event.preventDefault();
              actions.onOpen(task.id);
            }}
          >
            {t("handover.continue")}
          </ButtonLink>
          {task.allowed_actions?.includes("delete") ? (
            <Button type="button" size="sm" variant="ghost-danger" onClick={() => actions.onDelete(task)}>
              {t("common.delete")}
            </Button>
          ) : null}
        </>
      ),
    }),
  ];
}

import { ArrowRight } from "lucide-react";
import { useMemo } from "react";

import {
  AppTable,
  type ColumnsType,
  type ServerSortState,
  type UseServerTableResult,
} from "../../../components/antd/AppTable";
import {
  RowActionButton,
  RowActionLink,
  actionsColumn,
  serverColumn,
  serverSortColumn,
  statusColumn,
  textColumn,
  userColumn,
} from "../../../components/antd/columns";
import { useI18n } from "../../../i18n/I18nProvider";
import type { PersonRow } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";
import { PERSON_STATUSES, type HandoverKind } from "./consolePeopleModel";
import { personStatusLabel, personStatusTone } from "./lifecycleLabels";

export interface PeopleRowActions {
  onOpenHandover: (taskId: number) => void;
  onStart: (person: PersonRow, kind: HandoverKind) => void;
}

export function ConsolePeopleTable({
  people,
  isLoading,
  tableProps,
  filters,
  sort,
  actions,
}: {
  people: PersonRow[];
  isLoading: boolean;
  tableProps: UseServerTableResult<PersonRow>["tableProps"];
  /** 列 key -> 已选筛选值, 来自 useServerTable 的查询状态(status 在后端筛)。 */
  filters: Record<string, string[]>;
  /** 当前排序, 来自同一份查询状态(四列都在后端排)。 */
  sort: ServerSortState;
  actions: PeopleRowActions;
}) {
  const { t } = useI18n();
  const columns = useMemo(() => peopleColumns(t, filters, sort, actions), [actions, filters, sort, t]);

  return (
    <AppTable<PersonRow>
      {...tableProps}
      columns={columns}
      dataSource={people}
      emptyDescription={t("people.empty.description")}
      emptyTitle={t("people.empty.title")}
      loading={isLoading}
      minWidth={960}
      rowKey="user_id"
    />
  );
}

/**
 * 四列(姓名/部门/邮箱/状态)都在后端排(`ordering=name|department|email|status`),
 * 因此一律过 `serverSortColumn`: 客户端比较函数只会重排当前页, 与「共 N 条」矛盾。
 */
function peopleColumns(
  t: Translator,
  filters: Record<string, string[]>,
  sort: ServerSortState,
  actions: PeopleRowActions,
): ColumnsType<PersonRow> {
  return [
    serverSortColumn(
      userColumn<PersonRow>({
        key: "name",
        title: t("people.column.name"),
        getName: (person) => person.name || person.user_id,
        getUserId: (person) => person.user_id,
      }),
      sort,
    ),
    // 部门与邮箱后端不支持单列过滤(它们由工具栏的 q 一起做跨列搜索), 但支持排序。
    serverSortColumn(
      textColumn<PersonRow>({ key: "department", title: t("people.column.department"), width: 180 }),
      sort,
    ),
    serverSortColumn(
      textColumn<PersonRow>({ key: "email", title: t("people.column.email"), width: 240 }),
      sort,
    ),
    // status 在后端筛: serverColumn 去掉客户端 onFilter(否则 placeholderData 保留的
    // 上一页会被就地筛空)并受控 filteredValue; 默认单选, 与后端只认单个 status 一致。
    serverSortColumn(
      serverColumn(
        statusColumn<PersonRow>({
          key: "status",
          title: t("common.status"),
          options: PERSON_STATUSES.map((status) => ({
            value: status,
            label: personStatusLabel(t, status),
            tone: personStatusTone(status),
          })),
          width: 140,
        }),
        filters.status,
      ),
      sort,
    ),
    actionsColumn<PersonRow>({ render: (person) => <PeopleRowActionsCell person={person} actions={actions} /> }),
  ];
}

function PeopleRowActionsCell({ person, actions }: { person: PersonRow; actions: PeopleRowActions }) {
  const { t } = useI18n();
  // 已有进行中的交接单(不限在职状态)直接进入交接, 避免重复建单的困惑。
  if (person.open_handover_task_id) {
    return (
      <RowActionLink
        href={`/console/lifecycle/handover-tasks/${person.open_handover_task_id}`}
        icon={<ArrowRight size={15} />}
        onClick={(event) => {
          event.preventDefault();
          actions.onOpenHandover(person.open_handover_task_id as number);
        }}
      >
        {t("people.goHandover")}
      </RowActionLink>
    );
  }
  if (person.status !== "active") {
    return null;
  }
  return (
    <>
      <RowActionButton type="button" onClick={() => actions.onStart(person, "offboard")}>
        {t("people.startOffboard")}
      </RowActionButton>
      <RowActionButton type="button" onClick={() => actions.onStart(person, "transfer")}>
        {t("people.startTransfer")}
      </RowActionButton>
    </>
  );
}

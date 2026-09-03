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
  onOpenPermissions: (person: PersonRow) => void;
}

/** 管理员列的枚举值; 只用于让 statusColumn 渲染徽章, 不是后端字段的取值。 */
const CONSOLE_ADMIN_VALUE = "yes";

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
      // 固定布局下每列都必须声明宽度, minWidth 必须正好等于它们的和, 否则没宽度的列
      // 只能分摊剩余量, 剩余量不够时会被压成一个字宽。
      // 姓名 260 + 部门 180 + 邮箱 240 + 状态 140 + 管理员 90 + 操作 280 = 1190。
      minWidth={1190}
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
        // 次行是 36 位 UUID(truncate 展示), 260 够放下姓名与一段可辨认的前缀。
        width: 260,
      }),
      sort,
    ),
    // 管理员是只读展示: 后端 GET /users 不支持按它筛选也不支持按它排序,
    // 所以既不套 serverColumn 也不套 serverSortColumn, 并显式关掉内建筛选下拉;
    // 写入只走行内「权限」弹窗。非管理员按 statusColumn 的空值约定展示 "-"。
    // 位置紧跟姓名: 操作列是 fixed: "right" 的粘性列, 排在它前面的列在默认视口下会被
    // 压在粘性列底下要横向滚动才看得见, 而这一列的意义正是「不点开就能一眼扫出谁是管理员」。
    statusColumn<PersonRow>({
      key: "is_console_admin",
      title: t("people.column.consoleAdmin"),
      getValue: (person) => (person.is_console_admin ? CONSOLE_ADMIN_VALUE : ""),
      options: [{ value: CONSOLE_ADMIN_VALUE, label: t("people.consoleAdmin.yes"), tone: "bond" }],
      filter: false,
      width: 90,
    }),
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
    // 一行最多三个按钮(离职交接 / 转岗 / 权限)。宽度按英文实测取: 三个按钮 228px
    // + 两个间距 12px + 单元格左右内边距 24px = 264, 取 280 留余量;
    // 240 时英文标签会压到「管理员」列上(中文放得下, 只有英文会溢出)。
    actionsColumn<PersonRow>({
      width: 280,
      render: (person) => <PeopleRowActionsCell person={person} actions={actions} />,
    }),
  ];
}

function PeopleRowActionsCell({ person, actions }: { person: PersonRow; actions: PeopleRowActions }) {
  const { t } = useI18n();
  return (
    <>
      <PeopleHandoverAction person={person} actions={actions} />
      {/* 管理员身份与在职状态无关(已停用/已离职的账号也可能仍挂着管理员), 因此每行都给「权限」入口。 */}
      <RowActionButton type="button" onClick={() => actions.onOpenPermissions(person)}>
        {t("people.permissions")}
      </RowActionButton>
    </>
  );
}

function PeopleHandoverAction({ person, actions }: { person: PersonRow; actions: PeopleRowActions }) {
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

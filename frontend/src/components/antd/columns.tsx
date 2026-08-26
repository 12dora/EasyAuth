import type { ComponentPropsWithoutRef, MouseEvent, ReactNode } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import type { BadgeTone } from "../../lib/status";
import { Badge } from "../Badge";
import { Button } from "../Button";
import { ButtonLink } from "../ButtonLink";
import { enumFilter, readField, textFilter, type ColumnType, type ServerSortState } from "./AppTable";

/**
 * 表格里等宽文本(app_key / user_id / 版本号等标识符)的唯一样式出处。
 * 门户权限选择表格(按架构约定直接渲染原生 table)也从这里取, 避免两处字面量漂移。
 */
export const MONO_TEXT_CLASS = "font-mono text-body leading-5 text-ink-soft";

/**
 * 共享列预设。页面只声明「这列是什么语义」, 渲染、筛选、排序、宽度、
 * 对齐全部由这里决定; 以后要改表格里的状态徽章或时间格式, 只改这个文件。
 *
 * 约定: `title` 由调用方传已本地化的节点(页面本来就有自己的列名文案);
 * 预设自身需要的文案(操作列标题、筛选下拉、用户列兜底标题)走 `table.*` i18n。
 */

/* ------------------------------------------------------------------ */
/* 服务端筛选列                                                        */
/* ------------------------------------------------------------------ */

export interface ServerColumnOptions {
  /**
   * 允许多选(仅对 antd 内建 `filters` 下拉有意义)。
   * 默认 false: `filtersToParams` 默认只取第一个选中值, 多选会被静默丢弃,
   * 因此下拉也应该只让选一个。后端确实支持多值(配 `ServerFilterParam.multiple`)时传 true。
   */
  multiple?: boolean;
}

/**
 * 把任意列改造成「服务端筛选」列。
 *
 * 必须做两件事, 少一件都会出错:
 * 1. 去掉列预设自带的客户端 `onFilter` —— antd 在受控筛选(`filteredValue`)下**依然**
 *    会执行 `onFilter`, 于是后端已经筛过的当前页会被再筛一遍; 审计的 app_key 藏在
 *    metadata 里、列上读不到, 客户端再筛会把整页筛空;
 * 2. 用 `filteredValue` 受控 —— 筛选值的真相在 URL / 查询状态里, 不能留给 antd 内部
 *    状态, 否则刷新或深链后表头筛选图标会与实际请求参数对不上(`null` 表示未筛选)。
 *
 * ```tsx
 * serverColumn(textColumn<Row>({ key: "app_key", title: t("common.app"), filter: true }), filters.app_key)
 * ```
 */
export function serverColumn<T>(
  column: ColumnType<T>,
  filteredValue?: readonly string[] | null,
  options: ServerColumnOptions = {},
): ColumnType<T> {
  const { multiple = false } = options;
  return {
    ...column,
    onFilter: undefined,
    filteredValue: filteredValue !== undefined && filteredValue !== null && filteredValue.length > 0 ? [...filteredValue] : null,
    // filterMultiple 只影响 antd 内建下拉; 自定义 filterDropdown(文本/时间范围)不受它管。
    ...(column.filters ? { filterMultiple: multiple } : {}),
  };
}

/* ------------------------------------------------------------------ */
/* 服务端排序列                                                        */
/* ------------------------------------------------------------------ */

/**
 * 把任意列改造成「服务端排序」列。和 `serverColumn` 之于筛选是同一件事:
 *
 * 1. `sorter: true` —— 服务端模式的开关, **不带比较函数**。列预设自带的比较函数
 *    (`dateTimeColumn` 默认按时间戳、`textColumn({ sorter: true })` 按 localeCompare)
 *    只对「当前页那几行」生效, 在服务端分页表上是错的: 表头写着按时间倒序,
 *    实际只是把第 2 页内部重排了一遍。传进来的列若还带着比较函数, 这里会覆盖掉。
 * 2. `sortOrder` 受控 —— 排序的真相在 `useServerTable().query` 里(它就是请求参数的
 *    来源), 交给 antd 内部状态会让表头指示器和实际 `ordering` 参数对不上;
 *    别的列在排序时本列必须显式回到 `null`, 否则会同时亮起两个指示器。
 *
 * ```tsx
 * serverSortColumn(dateTimeColumn<Row>({ key: "created_at", title: t("...") }), sort)
 * ```
 */
export function serverSortColumn<T>(column: ColumnType<T>, sort: ServerSortState): ColumnType<T> {
  return {
    ...column,
    sorter: true,
    sortOrder: sort.sortField !== undefined && String(column.key) === sort.sortField ? (sort.sortOrder ?? null) : null,
  };
}

/* ------------------------------------------------------------------ */
/* 状态列                                                              */
/* ------------------------------------------------------------------ */

export interface StatusColumnOption {
  value: string;
  /** 已本地化的展示文案。 */
  label: ReactNode;
  /** 复用 Badge 的色调; 缺省 neutral。 */
  tone?: BadgeTone;
}

export interface StatusColumnConfig<T> {
  /** 列 key, 同时作为默认取值字段。 */
  key: string;
  title: ReactNode;
  options: readonly StatusColumnOption[];
  /** 默认读 `record[key]`。 */
  getValue?: (record: T) => string | null | undefined;
  width?: number;
  /** 关闭内建的枚举筛选(默认开启)。 */
  filter?: boolean;
}

/**
 * 状态列: Badge 渲染 + 内建 enumFilter。
 * 未在 options 里出现的值按 neutral 原样展示, 空值展示 "-"。
 */
export function statusColumn<T>({
  filter = true,
  getValue,
  key,
  options,
  title,
  width,
}: StatusColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => {
    const raw = getValue ? getValue(record) : readField(record, key);
    return raw === null || raw === undefined || raw === "" ? undefined : String(raw);
  };

  return {
    key,
    dataIndex: key,
    title,
    width,
    render: (_value: unknown, record: T) => {
      const value = read(record);
      if (value === undefined) {
        return "-";
      }
      const option = options.find((item) => item.value === value);
      return <Badge tone={option?.tone ?? "neutral"}>{option?.label ?? value}</Badge>;
    },
    ...(filter
      ? enumFilter<T>(
          key,
          options.map((option) => ({ label: option.label, value: option.value })),
          { getValue: (record) => read(record) ?? null },
        )
      : {}),
  };
}

/* ------------------------------------------------------------------ */
/* 时间列                                                              */
/* ------------------------------------------------------------------ */

export interface DateTimeColumnConfig<T> {
  key: string;
  title: ReactNode;
  /** 默认读 `record[key]`; 返回 ISO 字符串。 */
  getValue?: (record: T) => string | null | undefined;
  width?: number;
  /** 关闭排序(默认开启, 按时间戳升降序)。 */
  sorter?: boolean;
}

/** 时间列: 走 I18nProvider 的 formatDateTime(跟随界面语言) + 时间戳排序。 */
export function dateTimeColumn<T>({
  getValue,
  key,
  sorter = true,
  title,
  width = 170,
}: DateTimeColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => {
    const raw = getValue ? getValue(record) : readField(record, key);
    return raw === null || raw === undefined ? undefined : String(raw);
  };

  return {
    key,
    dataIndex: key,
    title,
    width,
    render: (_value: unknown, record: T) => <DateTimeCell value={read(record)} />,
    ...(sorter ? { sorter: (a: T, b: T) => timestamp(read(a)) - timestamp(read(b)) } : {}),
  };
}

function DateTimeCell({ value }: { value: string | undefined }) {
  const { formatDateTime } = useI18n();
  return <span className="whitespace-nowrap tabular">{formatDateTime(value)}</span>;
}

function timestamp(value: string | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

/* ------------------------------------------------------------------ */
/* 文本列                                                              */
/* ------------------------------------------------------------------ */

export interface TextColumnConfig<T> {
  key: string;
  title: ReactNode;
  /** 默认读 `record[key]`。 */
  getValue?: (record: T) => string | null | undefined;
  /** 开启文本子串筛选。 */
  filter?: boolean;
  /** 开启本地化字符串排序。 */
  sorter?: boolean;
  /** 超宽省略(默认开启), 关闭后长文本会撑高行。 */
  ellipsis?: boolean;
  /** 等宽字体展示(应用 key、ID 之类)。 */
  mono?: boolean;
  width?: number;
}

/** 普通文本列; 空值统一展示 "-"。 */
export function textColumn<T>({
  ellipsis = true,
  filter = false,
  getValue,
  key,
  mono = false,
  sorter = false,
  title,
  width,
}: TextColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => {
    const raw = getValue ? getValue(record) : readField(record, key);
    return raw === null || raw === undefined ? "" : String(raw);
  };

  return {
    key,
    dataIndex: key,
    title,
    width,
    ellipsis,
    render: (_value: unknown, record: T) => {
      const value = read(record);
      if (value === "") {
        return "-";
      }
      return mono ? <code className={MONO_TEXT_CLASS}>{value}</code> : value;
    },
    ...(filter ? textFilter<T>(key, { getValue: (record) => read(record) }) : {}),
    ...(sorter ? { sorter: (a: T, b: T) => read(a).localeCompare(read(b)) } : {}),
  };
}

/* ------------------------------------------------------------------ */
/* 用户列                                                              */
/* ------------------------------------------------------------------ */

export interface UserColumnConfig<T> {
  key?: string;
  title?: ReactNode;
  /** 主行: 显示名。 */
  getName: (record: T) => string | null | undefined;
  /** 次行: 用户 ID / 账号, 等宽展示; 不传则只渲染一行。 */
  getUserId?: (record: T) => string | null | undefined;
  /** 开启文本筛选(同时匹配显示名与 ID)。 */
  filter?: boolean;
  width?: number;
}

/**
 * 用户列: 显示名 + 等宽 ID 两行。
 * 沿用 ConsoleTeamMemberTable / MembershipsPanel 既有的成员单元格排版,
 * 仓库里没有表格内头像的先例, 因此不渲染头像。
 */
export function userColumn<T>({
  filter = false,
  getName,
  getUserId,
  key = "user",
  title,
  width,
}: UserColumnConfig<T>): ColumnType<T> {
  const read = (record: T) => {
    const name = getName(record);
    const userId = getUserId?.(record);
    return {
      name: name === null || name === undefined ? "" : String(name),
      userId: userId === null || userId === undefined ? "" : String(userId),
    };
  };

  return {
    key,
    title: title ?? <UserColumnTitle />,
    width,
    render: (_value: unknown, record: T) => {
      const { name, userId } = read(record);
      if (name === "" && userId === "") {
        return "-";
      }
      return (
        <div className="flex min-w-0 flex-col gap-1">
          <strong className="truncate">{name || userId}</strong>
          {userId && name ? <code className={cn(MONO_TEXT_CLASS, "truncate")}>{userId}</code> : null}
        </div>
      );
    },
    ...(filter
      ? textFilter<T>(key, {
          getValue: (record) => {
            const { name, userId } = read(record);
            return `${name} ${userId}`;
          },
        })
      : {}),
  };
}

function UserColumnTitle() {
  const { t } = useI18n();
  return <>{t("table.column.user")}</>;
}

/* ------------------------------------------------------------------ */
/* 操作列                                                              */
/* ------------------------------------------------------------------ */

/**
 * 操作列默认宽度: 三个两字 `size="sm"` 按钮(47px)+ 两道 6px 间距 + 单元格左右内边距(12+12)。
 * `tableLayout: "fixed"` 下列宽只能来自 `<colgroup>`, 所以操作列必须有一个真实宽度,
 * 不能再靠「收缩到内容」。
 */
export const ACTIONS_COLUMN_DEFAULT_WIDTH = 180;

export interface ActionsColumnConfig<T> {
  render: (record: T, index: number) => ReactNode;
  title?: ReactNode;
  /**
   * 列宽; 默认 `ACTIONS_COLUMN_DEFAULT_WIDTH`(够放三个两字按钮)。
   *
   * AppTable 固定用 `tableLayout: "fixed"`, 列宽只认 `<colgroup>`,
   * 旧的 `width: 1` + `w-0`(auto 布局下的「收缩到内容」写法)在 fixed 布局里
   * 会被原样当成 1px, 于是操作按钮整列溢出到相邻单元格上。
   * 按钮多于三个(或标签更长)时页面显式传实际宽度。
   */
  width?: number;
  /** 默认固定在右侧; 需要 AppTable 传 minWidth 才会生效。 */
  fixed?: ColumnType<T>["fixed"];
  key?: string;
}

/**
 * 操作列: 右对齐、不换行、固定右侧, 内部按钮点击不冒泡到行点击。
 * 按钮本身用 `RowActionButton` / `RowActionLink`(见下), 页面里不要再写
 * 裸的 `<Button size="sm" ...>` / `<ButtonLink size="sm" ...>`。
 */
export function actionsColumn<T>({
  fixed = "right",
  key = "actions",
  render,
  title,
  width = ACTIONS_COLUMN_DEFAULT_WIDTH,
}: ActionsColumnConfig<T>): ColumnType<T> {
  return {
    key,
    title: title ?? <ActionsColumnTitle />,
    fixed,
    width,
    align: "right",
    className: "whitespace-nowrap",
    render: (_value: unknown, record: T, index: number) => (
      <div className="flex items-center justify-end gap-1.5" onClick={stopRowClick} onDoubleClick={stopRowClick}>
        {render(record, index)}
      </div>
    ),
  };
}

function ActionsColumnTitle() {
  const { t } = useI18n();
  return <>{t("common.actions")}</>;
}

function stopRowClick(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
}

/** 行内操作按钮支持的两种语气: 普通与破坏性。 */
export type RowActionVariant = "ghost" | "ghost-danger";

/**
 * 表格行内操作按钮: 仓库自研 Button 的 `size="sm"`(h-7, 与分页控件的 28px 对齐)预设。
 *
 * 「点击不冒泡到行」由 actionsColumn 的容器负责, 所以这里只固定尺寸与语气;
 * 工作区四个页签包、矩阵、目录面板都用它, 页面里不要再各写一份。
 */
export function RowActionButton({
  variant = "ghost",
  ...props
}: Omit<ComponentPropsWithoutRef<typeof Button>, "size" | "variant"> & { variant?: RowActionVariant }) {
  return <Button size="sm" variant={variant} {...props} />;
}

/**
 * 表格行内操作链接: `RowActionButton` 的 `<a>` 版本(`components/ButtonLink` 的
 * `size="sm"` 预设)。「进入 / 查看 / 继续」这类跳转必须是真链接, 才能中键新开、
 * 复制地址、被爬到; 但它和同一格里的按钮共用 h-7 的尺寸与 ghost 语气。
 *
 * `href` + `onClick(preventDefault)` 的路由内跳转与 `to` 的 `<Link>` 两种写法
 * ButtonLink 都支持, 这里原样透传, 只锁死 size 与 variant 的取值域。
 */
export function RowActionLink({
  variant = "ghost",
  ...props
}: Omit<ComponentPropsWithoutRef<typeof ButtonLink>, "size" | "variant"> & { variant?: RowActionVariant }) {
  return <ButtonLink size="sm" variant={variant} {...props} />;
}

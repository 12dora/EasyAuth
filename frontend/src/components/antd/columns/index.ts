/**
 * 共享列预设。页面只声明「这列是什么语义」, 渲染、筛选、排序、宽度、
 * 对齐全部由这里决定; 以后要改表格里的状态徽章或时间格式, 只改这个目录。
 *
 * 约定: `title` 由调用方传已本地化的节点(页面本来就有自己的列名文案);
 * 预设自身需要的文案(操作列标题、筛选下拉、用户列兜底标题)走 `table.*` i18n。
 */

export {
  ACTIONS_COLUMN_DEFAULT_WIDTH,
  actionsColumn,
  RowActionButton,
  RowActionLink,
  type ActionsColumnConfig,
  type RowActionVariant,
} from "./actions";
export { appColumn, type AppColumnConfig } from "./app";
export {
  comparePersonLines,
  peopleColumn,
  personColumn,
  PERSON_SORT_LOCALE,
  userColumn,
  type PeopleColumnConfig,
  type PersonColumnConfig,
  type UserColumnConfig,
} from "./person";
export {
  activeStatusColumn,
  compareStatusByOptionIndex,
  statusColumn,
  type StatusColumnConfig,
  type StatusColumnOption,
} from "./status";
export {
  dateTimeColumn,
  MONO_TEXT_CLASS,
  MONO_WRAP_TEXT_CLASS,
  serverColumn,
  serverSortColumn,
  textColumn,
  type DateTimeColumnConfig,
  type ServerColumnOptions,
  type TextColumnConfig,
} from "./text";

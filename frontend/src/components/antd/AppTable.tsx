import { Table } from "antd";
import type { TablePaginationConfig, TableProps } from "antd";
import type {
  ColumnGroupType,
  ColumnType,
  ColumnsType,
  FilterDropdownProps,
  FilterValue,
  SorterResult,
  SortOrder,
  TableCurrentDataSource,
} from "antd/es/table/interface";
import { useMemo, type ReactNode } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import { EmptyState } from "../ui/EmptyState";
import {
  APP_TABLE_DEFAULT_PAGE_SIZE,
  APP_TABLE_PAGE_SIZE_OPTIONS,
  APP_TABLE_PAGINATION_CLASS,
} from "./useServerTable";

export type { ColumnGroupType, ColumnType, ColumnsType, TablePaginationConfig, TableProps };
/**
 * antd 表格的「回调签名」类型。页面写自定义 filterDropdown 或 onChange 时需要它们,
 * 但 `antd/es/table/*` 是内部路径(迁移护栏 FORBIDDEN_ANTD_TABLE_IMPORT 也禁止页面直接引),
 * 所以统一从这里再导出。
 */
export type { FilterDropdownProps, FilterValue, SortOrder, SorterResult, TableCurrentDataSource };

export { APP_TABLE_PAGE_SIZE_OPTIONS, APP_TABLE_DEFAULT_PAGE_SIZE, APP_TABLE_PAGINATION_CLASS };

export interface AppTableProps<T> extends Omit<TableProps<T>, "rowKey" | "pagination" | "locale" | "caption"> {
  /** 必填: 行身份只能来自数据字段, 不允许回落数组下标。 */
  rowKey: NonNullable<TableProps<T>["rowKey"]>;
  /**
   * 表格的无障碍名字, 渲染成视觉隐藏的原生 `<caption>`。
   *
   * 一个页面上有多张表(门户的授权/申请/审批)时, 屏幕阅读器只会念 "table",
   * 用户无从分辨; `<caption>` 是 HTML 给表格命名的原生方式, 直接成为
   * `role="table"` 的可及名称, 不需要额外的 aria 属性。
   * 隐藏样式在 `src/styles/features/app-table.css` 的 `.ant-table-caption`
   * (用 clip 而不是 display:none, 否则名字会一起从无障碍树里消失)。
   */
  ariaLabel?: string;
  /**
   * 表格的最小宽度, 写进 `scroll.x`。列宽之和已经确定时传像素数。
   *
   * 有行数据时不传也**始终**有 `scroll.x`(回落 "max-content"): 横向滚动必须落在 antd
   * 自己的 `.ant-table-content` 上, 否则超宽表格会把整页撑出横向滚动条; 而且 fixed 布局下
   * 没有剩余宽度时无宽度列会被压到 0px, "max-content" 让它们退回内容宽度。
   * 表格样式里的 `min-width: 100%` 由 antd 写死, 宽屏下仍然铺满容器。
   *
   * 空表例外, 见 `mergedScroll` 的注释。
   */
  minWidth?: number | "max-content";
  /**
   * 客户端模式: 省略或只覆盖展示项, antd 自己分页/排序/筛选。
   * 服务端模式: 展开 `useServerTable().tableProps`。
   * 传 false 关闭分页。
   * 分页样式由 AppTable 统一决定, 页面只该传 current/pageSize/total。
   */
  pagination?: TablePaginationConfig | false;
  /** 空态标题; 缺省用 i18n 的「暂无数据」。 */
  emptyTitle?: string;
  emptyDescription?: string;
  emptyIcon?: ReactNode;
  emptyAction?: ReactNode;
  /** 需要完全自定义空态时传节点, 会覆盖上面四个字段。 */
  empty?: ReactNode;
}

/**
 * 全站数据表格的唯一入口。所有布局约定都在这里, 页面不再重复:
 * w-full、size="middle"、tableLayout="fixed"、rowKey 必填、
 * 行高(主题 Table token)、空态(复用 EmptyState)、加载态、单行分页。
 *
 * 分页显式写死 size="small": antd 在 size="middle" 的表格下本来也会把分页降为
 * small, 显式写出来是为了让「页码按钮」和「每页条数 Select」同时取
 * controlHeightSM(28px, 等于 Button size="sm" 的 h-7), 不依赖 antd 内部联动。
 */
export function AppTable<T extends object>({
  ariaLabel,
  className,
  dataSource,
  empty,
  emptyAction,
  emptyDescription,
  emptyIcon,
  emptyTitle,
  minWidth,
  pagination,
  rowKey,
  scroll,
  size = "middle",
  sticky = false,
  tableLayout = "fixed",
  ...rest
}: AppTableProps<T>) {
  const { t } = useI18n();

  const mergedPagination = useMemo<TablePaginationConfig | false>(() => {
    if (pagination === false) {
      return false;
    }
    return {
      defaultPageSize: APP_TABLE_DEFAULT_PAGE_SIZE,
      pageSizeOptions: [...APP_TABLE_PAGE_SIZE_OPTIONS],
      position: ["bottomRight"],
      showSizeChanger: true,
      size: "small",
      showTotal: (total, range) => t("table.pagination.total", { start: range[0], end: range[1], total }),
      ...pagination,
      // 页面即使自己传了 className 也不能丢掉「单行分页」约定, 因此合并在展开之后。
      className: cn(APP_TABLE_PAGINATION_CLASS, pagination?.className),
    };
  }, [pagination, t]);

  const isEmpty = (dataSource?.length ?? 0) === 0;

  /*
   * scroll.x 一定要有值: 它是 antd 给 `.ant-table-content` 挂 overflow-x:auto 的开关,
   * 少了它超宽表格会把整页撑出横向滚动条。有行数据时宽度取页面显式传的 scroll.x,
   * 其次 minWidth, 都没有就用 "max-content"(列按内容取宽, 表格自身仍带 min-width:100%)。
   *
   * 空表是唯一例外: minWidth 要让位给 `true`(= 只要滚动容器, 表格宽度交给布局),
   * 否则空态框会和表头错位。开了横向滚动后 rc-table 把空态包进
   * `.ant-table-expanded-row-fixed`, 给它写死 `width: <容器宽度>px; position: sticky; left: 0`
   * —— 空态框钉在可视区、宽度是容器宽, 而表头那张 `<table>` 被 minWidth 撑到更宽
   * (人员管理: 容器 860 / 表头 960)。于是没有一行数据的表格也带一条横向滚动条,
   * 一滚表头整排移动、空态框纹丝不动, 末尾的「操作」列还被 sticky 钉在右侧盖住相邻列。
   * 而空表本来就没有行内容需要 minWidth 去保住列宽 —— 表头只是个图例。
   * 换成 `x: true` 后表格按 `table-layout: fixed` 正好铺满容器, 表头与空态框同宽同起点;
   * 容器窄到连各列声明的宽度都放不下时表格仍会溢出, 那时滚动容器还在,
   * 「页面永不横向滚动」的约定不受影响。
   */
  const mergedScroll = useMemo<TableProps<T>["scroll"]>(() => {
    if (isEmpty) {
      return { ...scroll, x: true };
    }
    return { ...scroll, x: scroll?.x ?? minWidth ?? "max-content" };
  }, [isEmpty, minWidth, scroll]);

  const locale = useMemo(
    () => ({
      emptyText: empty ?? (
        <EmptyState
          action={emptyAction}
          description={emptyDescription}
          icon={emptyIcon}
          title={emptyTitle ?? t("table.empty.title")}
        />
      ),
    }),
    [empty, emptyAction, emptyDescription, emptyIcon, emptyTitle, t],
  );

  return (
    <Table<T>
      caption={ariaLabel}
      className={cn("w-full", className)}
      dataSource={dataSource}
      locale={locale}
      pagination={mergedPagination}
      rowKey={rowKey}
      scroll={mergedScroll}
      size={size}
      sticky={sticky}
      tableLayout={tableLayout}
      {...rest}
    />
  );
}

export {
  filtersToParams,
  serverTableQuery,
  tablePropsWithTotal,
  useServerTable,
  type ServerFilterParam,
  type ServerFilterParamMap,
  type ServerSortState,
  type ServerSortValue,
  type ServerTableParams,
  type ServerTableQuery,
  type UseServerTableOptions,
  type UseServerTableResult,
} from "./useServerTable";

export {
  ORDERING_PARAM,
  orderingSerializer,
  parseOrderingParam,
  searchParamsWithOrdering,
  sortStateFromOrdering,
  sortValueFromSorter,
  type OrderingFieldMap,
} from "./ordering";

export {
  DATE_RANGE_CONTROL_WIDTH_PX,
  DateRangeControl,
  dateRangeFilter,
  decodeDateRange,
  encodeDateRange,
  enumFilter,
  readField,
  textFilter,
  type DateRangeControlProps,
  type DateRangeFilterColumn,
  type DateRangeFilterOptions,
  type DateRangeValue,
  type EnumFilterColumn,
  type EnumFilterOption,
  type EnumFilterOptions,
  type TextFilterColumn,
  type TextFilterOptions,
} from "./tableFilters";

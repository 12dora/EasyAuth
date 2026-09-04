/*
 * 权限选择表格的表级可变状态。
 *
 * flexRender 把 columnDef.header / columnDef.cell 直接当成组件类型渲染, 列定义一重建,
 * React 就把每一格的子树当成"换了组件"整体卸载重挂: 按钮与勾选框都换成新 DOM 节点,
 * 焦点丢掉, 落在按下与松开之间的那次点击也丢掉。所以列定义必须是模块级常量,
 * 会变的状态(勾选态、覆盖范围、回调、语言、禁用态)一律挂在 table.options.meta 上,
 * 由单元格在渲染时读取。
 */

import type { RowData, Table, TableMeta } from "@tanstack/react-table";

import type { Locale } from "../../../i18n/messages";
import type { Translator } from "../../../lib/status";

import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

declare module "@tanstack/react-table" {
  // 全仓库只有权限选择器一张 TanStack 表, meta 的形状因此直接声明在 TableMeta 上。
  interface TableMeta<TData extends RowData> {
    t: Translator;
    locale: Locale;
    /** 展示勾选态 = 直接勾选 ∪ 所选权限组覆盖; 提交载荷仍只用直接勾选。 */
    displaySelectedKeys: string[];
    /** 所选权限组覆盖的权限范围: 与直接勾选同样可点, 只在样式上标出来源。 */
    coveredKeySet: Set<string>;
    /**
     * 撤销申请里还允许勾上的权限范围(基础授权的直接权限 + 当前所选权限组的覆盖范围)。
     * 越界的 chip 必须真正 disabled: 撤销目标只能是基础授权的子集。null 表示不是撤销申请。
     */
    retainableKeySet: Set<string> | null;
    /** 仅看已选: 空态文案要跟着换。 */
    showSelectedOnly: boolean;
    disabled: boolean;
    onPermissionScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
    onPermissionGroupScopeChange: (
      group: ScopedPermissionGroupItem,
      scopeKey: string,
      shouldSelect: boolean,
    ) => void;
    onToggleGroup: (key: string) => void;
  }
}

export type PermissionSelectorTableMeta = TableMeta<PermissionSelectorRow>;

/** meta 缺失说明表格没按约定装配: 直接失败, 不猜默认值。 */
export function permissionSelectorTableMeta(table: Table<PermissionSelectorRow>): PermissionSelectorTableMeta {
  const meta = table.options.meta;
  if (!meta) {
    throw new Error("权限选择表格缺少 table.options.meta，单元格状态必须由 PermissionSelector 提供");
  }
  return meta;
}

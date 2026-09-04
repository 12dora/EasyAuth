/*
 * 权限选择表格的列定义: 模块级常量, 组件整个生命周期里身份不变。
 *
 * 表头与单元格渲染器同样是模块级组件, 只从 table.options.meta 读会变的状态
 * (见 permissionSelectorMeta.ts) —— 这样勾选一下不会重建列, 单元格 DOM 不再卸载重挂。
 */

import type { CellContext, ColumnDef, HeaderContext } from "@tanstack/react-table";

import { MONO_TEXT_CLASS } from "../../../components/antd/columns";

import {
  PermissionGroupNameCell,
  PermissionGroupScopeCell,
  PermissionNameCell,
  PermissionScopeCell,
} from "./PermissionSelectorCells";
import { permissionSelectorTableMeta } from "./permissionSelectorMeta";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

type SelectorHeaderContext = HeaderContext<PermissionSelectorRow, unknown>;
type SelectorCellContext = CellContext<PermissionSelectorRow, unknown>;

export const PERMISSION_SELECTOR_COLUMNS: ColumnDef<PermissionSelectorRow>[] = [
  { id: "permission", header: PermissionColumnHeader, cell: PermissionColumnCell },
  { id: "key", header: KeyColumnHeader, cell: KeyColumnCell },
  { id: "scope", header: ScopeColumnHeader, cell: ScopeColumnCell },
];

function PermissionColumnHeader({ table }: SelectorHeaderContext) {
  return permissionSelectorTableMeta(table).t("selector.column.permission");
}

function PermissionColumnCell({ row, table }: SelectorCellContext) {
  const { locale, onToggleGroup } = permissionSelectorTableMeta(table);
  return row.original.type === "group" ? (
    <PermissionGroupNameCell
      group={row.original.group}
      depth={row.original.depth}
      isExpanded={row.original.isExpanded}
      selectedCount={row.original.selectedCount}
      permissionCount={row.original.permissionCount}
      onToggleGroup={onToggleGroup}
      locale={locale}
    />
  ) : (
    <PermissionNameCell permission={row.original.permission} depth={row.original.depth} locale={locale} />
  );
}

function KeyColumnHeader({ table }: SelectorHeaderContext) {
  return permissionSelectorTableMeta(table).t("selector.column.key");
}

function KeyColumnCell({ row }: SelectorCellContext) {
  return (
    <code className={MONO_TEXT_CLASS}>
      {row.original.type === "group" ? row.original.group.key : row.original.permission.key}
    </code>
  );
}

function ScopeColumnHeader({ table }: SelectorHeaderContext) {
  return permissionSelectorTableMeta(table).t("selector.column.scope");
}

function ScopeColumnCell({ row, table }: SelectorCellContext) {
  const { locale, displaySelectedKeys, coveredKeySet, onPermissionScopeChange, onPermissionGroupScopeChange } =
    permissionSelectorTableMeta(table);
  return row.original.type === "group" ? (
    <PermissionGroupScopeCell
      group={row.original.group}
      scopeOptions={row.original.scopeOptions}
      selectedKeys={displaySelectedKeys}
      onScopeChange={onPermissionGroupScopeChange}
      locale={locale}
    />
  ) : (
    <PermissionScopeCell
      permission={row.original.permission}
      selectedKeys={displaySelectedKeys}
      coveredKeySet={coveredKeySet}
      onScopeChange={onPermissionScopeChange}
      locale={locale}
    />
  );
}

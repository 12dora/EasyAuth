import type { ColumnDef } from "@tanstack/react-table";

import { MONO_TEXT_CLASS } from "../../../components/ui/tableStyles";
import type { Locale } from "../../../i18n/messages";
import type { Translator } from "../../../lib/status";

import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import {
  PermissionGroupNameCell,
  PermissionGroupScopeCell,
  PermissionNameCell,
  PermissionScopeCell,
} from "./PermissionSelectorCells";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

/** 列定义所需的全部外部输入: 文案/语言 + 展示勾选态 + 三个回调。 */
export interface PermissionSelectorColumnsInput {
  t: Translator;
  locale: Locale;
  displaySelectedKeys: string[];
  coveredKeySet: Set<string>;
  onPermissionScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
  onPermissionGroupScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  onToggleGroup: (key: string) => void;
}

export function permissionSelectorColumns(input: PermissionSelectorColumnsInput): ColumnDef<PermissionSelectorRow>[] {
  return [nameColumn(input), keyColumn(input.t), scopeColumn(input)];
}

function nameColumn({ t, locale, onToggleGroup }: PermissionSelectorColumnsInput): ColumnDef<PermissionSelectorRow> {
  return {
    id: "permission",
    header: t("selector.column.permission"),
    cell: ({ row }) =>
      row.original.type === "group" ? (
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
      ),
  };
}

function keyColumn(t: Translator): ColumnDef<PermissionSelectorRow> {
  return {
    id: "key",
    header: t("selector.column.key"),
    cell: ({ row }) => (
      <code className={MONO_TEXT_CLASS}>
        {row.original.type === "group" ? row.original.group.key : row.original.permission.key}
      </code>
    ),
  };
}

function scopeColumn({
  t,
  locale,
  displaySelectedKeys,
  coveredKeySet,
  onPermissionScopeChange,
  onPermissionGroupScopeChange,
}: PermissionSelectorColumnsInput): ColumnDef<PermissionSelectorRow> {
  return {
    id: "scope",
    header: t("selector.column.scope"),
    cell: ({ row }) =>
      row.original.type === "group" ? (
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
      ),
  };
}

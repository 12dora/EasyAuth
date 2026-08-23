import type { ColumnDef } from "@tanstack/react-table";
import type { Dispatch, SetStateAction } from "react";

import { Badge } from "../../../../components/Badge";
import { SelectInput } from "../../../../components/Field";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import type { AuthorizationGroupGrantItem, AuthorizationGroupItem } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";
import { removeGrant, updateGrant, updateGrantManagedScopePolicy, type AuthorizationGroupForm } from "./grantFormUpdates";
import {
  isManagedUsersGrant,
  managedScopeEffectivePolicyLabel,
  managedScopeHealthLabel,
  managedScopeInheritedFromLabel,
  managedScopePolicyResolver,
} from "./managedScopePolicy";

export function authorizationGroupColumns({
  t,
  canManage,
  onEdit,
}: {
  t: Translator;
  canManage: boolean;
  onEdit: (group: AuthorizationGroupItem) => void;
}): ColumnDef<AuthorizationGroupItem>[] {
  return [
    { header: t("console.matrix.column.key"), cell: ({ row }) => <code>{row.original.key}</code> },
    { header: t("common.name"), accessorKey: "name" },
    { header: t("common.type"), cell: ({ row }) => (row.original.kind === "role" ? t("common.role") : row.original.kind === "bundle" ? t("console.matrix.kindBundle") : row.original.kind) },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={row.original.requestable ? "evergreen" : "neutral"}>{row.original.requestable ? t("console.matrix.requestable") : t("console.matrix.notRequestable")}</Badge>
          <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? t("common.enabled") : t("common.disabled")}</Badge>
        </div>
      ),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" disabled={!canManage} onClick={() => onEdit(row.original)}>
            {t("common.edit")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
}

export function authorizationGroupGrantColumns({
  t,
  canManage,
  setForm,
}: {
  t: Translator;
  canManage: boolean;
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>;
}): ColumnDef<AuthorizationGroupGrantItem>[] {
  return [
    { header: t("console.matrix.grant.column.item"), cell: ({ row }) => `${row.original.permission} / ${row.original.scope}` },
    {
      header: t("console.matrix.grant.column.managedScope"),
      cell: ({ row }) => {
        if (!isManagedUsersGrant(row.original)) {
          return "-";
        }
        return (
          <SelectInput
            aria-label={t("console.matrix.grant.managedScopeAriaLabel", { permission: row.original.permission, scope: row.original.scope })}
            value={managedScopePolicyResolver(row.original.managed_scope_policy)}
            onChange={(event) => updateGrantManagedScopePolicy(row.original, event.currentTarget.value, setForm)}
          >
            <option value="inherit">{t("console.matrix.grant.policy.inherit")}</option>
            <option value="dingtalk_manager_chain">{t("console.matrix.grant.policy.override")}</option>
            <option value="easyauth_team">{t("console.managedScope.option.team")}</option>
            <option value="union">{t("console.managedScope.option.union")}</option>
            <option value="disabled">{t("console.matrix.grant.policy.disabled")}</option>
          </SelectInput>
        );
      },
    },
    {
      header: t("console.matrix.grant.column.effective"),
      cell: ({ row }) => managedScopeEffectivePolicyLabel(t, row.original),
    },
    {
      header: t("console.matrix.grant.column.inheritedFrom"),
      cell: ({ row }) => managedScopeInheritedFromLabel(t, row.original),
    },
    {
      header: t("console.matrix.grant.column.health"),
      cell: ({ row }) => managedScopeHealthLabel(t, row.original),
    },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? t("common.enabled") : t("common.disabled")}</Badge> },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton
            type="button"
            variant={row.original.is_active ? "ghost-danger" : "ghost"}
            disabled={!canManage}
            onClick={() => updateGrant(row.original, !row.original.is_active, setForm)}
          >
            {row.original.is_active ? t("common.disable") : t("common.enable")}
          </TableRowActionButton>
          <TableRowActionButton type="button" variant="ghost-danger" disabled={!canManage} onClick={() => removeGrant(row.original, setForm)}>
            {t("common.remove")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
}

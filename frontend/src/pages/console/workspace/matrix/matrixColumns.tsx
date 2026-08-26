import type { Dispatch, SetStateAction } from "react";

import { Badge } from "../../../../components/Badge";
import { SelectInput } from "../../../../components/Field";
import { enumFilter, type ColumnsType } from "../../../../components/antd/AppTable";
import { RowActionButton, actionsColumn, textColumn } from "../../../../components/antd/columns";
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
}): ColumnsType<AuthorizationGroupItem> {
  return [
    textColumn<AuthorizationGroupItem>({
      key: "key",
      title: t("console.matrix.column.key"),
      mono: true,
      filter: true,
      width: 220,
    }),
    textColumn<AuthorizationGroupItem>({ key: "name", title: t("common.name"), filter: true, sorter: true }),
    {
      key: "kind",
      dataIndex: "kind",
      title: t("common.type"),
      width: 120,
      render: (_value: unknown, group: AuthorizationGroupItem) => authorizationGroupKindLabel(t, group.kind),
      ...enumFilter<AuthorizationGroupItem>("kind", [
        { label: t("common.role"), value: "role" },
        { label: t("console.matrix.kindBundle"), value: "bundle" },
      ]),
    },
    {
      key: "status",
      title: t("common.status"),
      width: 200,
      render: (_value: unknown, group: AuthorizationGroupItem) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={group.requestable ? "evergreen" : "neutral"}>
            {group.requestable ? t("console.matrix.requestable") : t("console.matrix.notRequestable")}
          </Badge>
          <Badge tone={group.is_active ? "evergreen" : "neutral"}>
            {group.is_active ? t("common.enabled") : t("common.disabled")}
          </Badge>
        </div>
      ),
      // 一个单元格里有「可申请」和「启用」两枚徽章, 所以筛选值是数组, 按「包含」匹配。
      ...enumFilter<AuthorizationGroupItem>(
        "status",
        [
          { label: t("common.enabled"), value: "active" },
          { label: t("common.disabled"), value: "inactive" },
          { label: t("console.matrix.requestable"), value: "requestable" },
          { label: t("console.matrix.notRequestable"), value: "not_requestable" },
        ],
        {
          getValue: (group) => [
            group.is_active ? "active" : "inactive",
            group.requestable ? "requestable" : "not_requestable",
          ],
        },
      ),
    },
    actionsColumn<AuthorizationGroupItem>({
      title: t("common.actions"),
      render: (group) => (
        <RowActionButton type="button" disabled={!canManage} onClick={() => onEdit(group)}>
          {t("common.edit")}
        </RowActionButton>
      ),
    }),
  ];
}

function authorizationGroupKindLabel(t: Translator, kind: string): string {
  if (kind === "role") {
    return t("common.role");
  }
  if (kind === "bundle") {
    return t("console.matrix.kindBundle");
  }
  return kind;
}

export function authorizationGroupGrantColumns({
  t,
  canManage,
  setForm,
}: {
  t: Translator;
  canManage: boolean;
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>;
}): ColumnsType<AuthorizationGroupGrantItem> {
  return [
    textColumn<AuthorizationGroupGrantItem>({
      key: "item",
      title: t("console.matrix.grant.column.item"),
      getValue: (grant) => `${grant.permission} / ${grant.scope}`,
      width: 200,
    }),
    {
      key: "managedScope",
      title: t("console.matrix.grant.column.managedScope"),
      width: 180,
      render: (_value: unknown, grant: AuthorizationGroupGrantItem) => {
        if (!isManagedUsersGrant(grant)) {
          return "-";
        }
        return (
          <SelectInput
            aria-label={t("console.matrix.grant.managedScopeAriaLabel", { permission: grant.permission, scope: grant.scope })}
            value={managedScopePolicyResolver(grant.managed_scope_policy)}
            onChange={(event) => updateGrantManagedScopePolicy(grant, event.currentTarget.value, setForm)}
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
      key: "effective",
      title: t("console.matrix.grant.column.effective"),
      width: 140,
      render: (_value: unknown, grant: AuthorizationGroupGrantItem) => managedScopeEffectivePolicyLabel(t, grant),
    },
    {
      key: "inheritedFrom",
      title: t("console.matrix.grant.column.inheritedFrom"),
      width: 120,
      render: (_value: unknown, grant: AuthorizationGroupGrantItem) => managedScopeInheritedFromLabel(t, grant),
    },
    {
      key: "health",
      title: t("console.matrix.grant.column.health"),
      width: 110,
      render: (_value: unknown, grant: AuthorizationGroupGrantItem) => managedScopeHealthLabel(t, grant),
    },
    {
      key: "status",
      dataIndex: "is_active",
      title: t("common.status"),
      width: 100,
      render: (_value: unknown, grant: AuthorizationGroupGrantItem) => (
        <Badge tone={grant.is_active ? "evergreen" : "neutral"}>
          {grant.is_active ? t("common.enabled") : t("common.disabled")}
        </Badge>
      ),
    },
    actionsColumn<AuthorizationGroupGrantItem>({
      title: t("common.actions"),
      render: (grant) => (
        <>
          <RowActionButton
            type="button"
            variant={grant.is_active ? "ghost-danger" : "ghost"}
            disabled={!canManage}
            onClick={() => updateGrant(grant, !grant.is_active, setForm)}
          >
            {grant.is_active ? t("common.disable") : t("common.enable")}
          </RowActionButton>
          <RowActionButton type="button" variant="ghost-danger" disabled={!canManage} onClick={() => removeGrant(grant, setForm)}>
            {t("common.remove")}
          </RowActionButton>
        </>
      ),
    }),
  ];
}

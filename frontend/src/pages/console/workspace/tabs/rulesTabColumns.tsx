import { enumFilter, textFilter, type ColumnsType } from "../../../../components/antd/AppTable";
import { RowActionButton, actionsColumn, textColumn } from "../../../../components/antd/columns";
import { Badge } from "../../../../components/Badge";
import { formatPeople, resolvePeople } from "../../../../components/UserCombobox";
import type { UserOption } from "../../../../components/UserCombobox";
import type { Translator } from "../../../../lib/status";
import {
  isBlocking,
  normalizeTargetType,
  targetTypeLabel,
  type EditableApprovalRule,
  type RuleFormState,
} from "./rulesTabModel";

export function buildRuleColumns({
  approverOptions,
  t,
  onEdit,
  onToggle,
  togglePending,
}: {
  approverOptions: UserOption[] | undefined;
  t: Translator;
  onEdit: (rule: EditableApprovalRule) => void;
  onToggle: (rule: EditableApprovalRule) => void;
  togglePending: boolean;
}): ColumnsType<EditableApprovalRule> {
  return [
    textColumn<EditableApprovalRule>({
      key: "target",
      title: t("console.rules.column.target"),
      getValue: (rule) => `${targetTypeLabel(t, rule.target_type)}\uff1a${rule.target_key ?? "-"}`,
      filter: true,
      sorter: true,
      width: 280,
    }),
    {
      key: "approvers",
      title: t("console.rules.column.approvers"),
      render: (_value: unknown, rule: EditableApprovalRule) =>
        formatPeople(resolvePeople(rule.approver_userids, approverOptions), t),
      sorter: (a: EditableApprovalRule, b: EditableApprovalRule) =>
        formatPeople(resolvePeople(a.approver_userids, approverOptions), t).localeCompare(
          formatPeople(resolvePeople(b.approver_userids, approverOptions), t),
        ),
      ...textFilter<EditableApprovalRule>("approvers", {
        getValue: (rule) => formatPeople(resolvePeople(rule.approver_userids, approverOptions), t),
      }),
    },
    {
      key: "status",
      title: t("common.status"),
      width: 180,
      sorter: (a: EditableApprovalRule, b: EditableApprovalRule) => {
        const active = Number(Boolean(b.is_active)) - Number(Boolean(a.is_active));
        if (active !== 0) {
          return active;
        }
        return Number(isBlocking(b)) - Number(isBlocking(a));
      },
      render: (_value: unknown, rule: EditableApprovalRule) => (
        <div className="flex flex-wrap gap-2">
          <Badge tone={rule.is_active ? "evergreen" : "neutral"}>{rule.is_active ? t("common.enabled") : t("common.disabled")}</Badge>
          {isBlocking(rule) ? <Badge tone="signal">{t("console.rules.blocking")}</Badge> : null}
        </div>
      ),
      // 单元格里可能同时有「启用」和「阻塞」两枚徽章, 因此筛选值是数组, 按「包含」匹配。
      ...enumFilter<EditableApprovalRule>(
        "status",
        [
          { label: t("common.enabled"), value: "active" },
          { label: t("common.disabled"), value: "inactive" },
          { label: t("console.rules.blocking"), value: "blocking" },
        ],
        {
          getValue: (rule) => [rule.is_active ? "active" : "inactive", ...(isBlocking(rule) ? ["blocking"] : [])],
        },
      ),
    },
    actionsColumn<EditableApprovalRule>({
      title: t("common.actions"),
      render: (rule) => (
        <>
          <RowActionButton
            type="button"
            onClick={() => {
              onEdit(rule);
            }}
          >
            {t("common.edit")}
          </RowActionButton>
          <RowActionButton
            type="button"
            variant={rule.is_active ? "ghost-danger" : "ghost"}
            onClick={() => onToggle(rule)}
            disabled={togglePending}
          >
            {rule.is_active ? t("common.disable") : t("common.enable")}
          </RowActionButton>
        </>
      ),
    }),
  ];
}

export function editFormFromRule(rule: EditableApprovalRule): RuleFormState {
  return {
    target_type: normalizeTargetType(rule.target_type),
    target_key: rule.target_key ?? "",
    approverUserIds: rule.approver_userids ?? [],
  };
}

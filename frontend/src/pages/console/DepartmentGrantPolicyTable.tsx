import { Tooltip } from "antd";
import { useMemo } from "react";

import { AppTable, type ColumnsType } from "../../components/antd/AppTable";
import { RowActionButton, actionsColumn, textColumn } from "../../components/antd/columns";
import { Badge } from "../../components/Badge";
import { useI18n } from "../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { departmentDisplayName } from "../../lib/departmentDisplayName";
import type { DepartmentGrantPolicy } from "../../lib/domain/departmentGrants";

/** 「授权内容」列最多平铺的徽章数, 其余收进 +N 的悬浮提示。 */
const VISIBLE_CHIP_COUNT = 3;

interface DepartmentGrantPolicyTableProps {
  policies: DepartmentGrantPolicy[];
  /** 取的是 isFetching: 换部门时上一份行留在原地转圈, 而不是先清空再重画。 */
  loading: boolean;
  /** 留在表格里的还是上一部门的行时为 true: 行内操作必须关掉, 加载遮罩挡不住键盘。 */
  actionsDisabled: boolean;
  onEdit: (policy: DepartmentGrantPolicy) => void;
  onDelete: (policy: DepartmentGrantPolicy) => void;
}

export function DepartmentGrantPolicyTable({
  policies,
  loading,
  actionsDisabled,
  onEdit,
  onDelete,
}: DepartmentGrantPolicyTableProps) {
  const { t, formatDateTime } = useI18n();

  const columns = useMemo<ColumnsType<DepartmentGrantPolicy>>(
    () => [
      {
        key: "app",
        title: t("departmentGrants.column.app"),
        width: 200,
        ellipsis: true,
        render: (_value: unknown, policy: DepartmentGrantPolicy) => formatAppDisplayName(policy.app),
      },
      {
        key: "content",
        title: t("departmentGrants.column.content"),
        width: 320,
        ellipsis: false,
        render: (_value: unknown, policy: DepartmentGrantPolicy) => <GrantContentCell policy={policy} />,
      },
      {
        key: "term",
        title: t("departmentGrants.column.term"),
        width: 170,
        render: (_value: unknown, policy: DepartmentGrantPolicy) => (
          <span className="whitespace-nowrap tabular">
            {policy.grant_type === "permanent" ? t("departmentGrants.term.permanent") : formatDateTime(policy.expires_at)}
          </span>
        ),
      },
      {
        key: "source",
        title: t("departmentGrants.column.source"),
        width: 180,
        render: (_value: unknown, policy: DepartmentGrantPolicy) => (
          <Badge tone="faint">
            {policy.inherited
              ? t("departmentGrants.source.inherited", { name: departmentDisplayName(policy.defined_on, t) })
              : t("departmentGrants.source.own")}
          </Badge>
        ),
      },
      {
        key: "affected_user_count",
        dataIndex: "affected_user_count",
        title: t("departmentGrants.column.affected"),
        width: 110,
        align: "right",
        render: (_value: unknown, policy: DepartmentGrantPolicy) => (
          <span className="tabular">{policy.affected_user_count}</span>
        ),
      },
      textColumn<DepartmentGrantPolicy>({
        key: "reason",
        title: t("departmentGrants.column.reason"),
        width: 200,
      }),
      actionsColumn<DepartmentGrantPolicy>({
        width: 150,
        render: (policy) => (
          <>
            <RowActionButton type="button" disabled={actionsDisabled} onClick={() => onEdit(policy)}>
              {t("common.edit")}
            </RowActionButton>
            <RowActionButton
              type="button"
              variant="ghost-danger"
              disabled={actionsDisabled}
              onClick={() => onDelete(policy)}
            >
              {t("common.delete")}
            </RowActionButton>
          </>
        ),
      }),
    ],
    [actionsDisabled, formatDateTime, onDelete, onEdit, t],
  );

  return (
    <AppTable<DepartmentGrantPolicy>
      rowKey="id"
      ariaLabel={t("departmentGrants.tableAriaLabel")}
      columns={columns}
      dataSource={policies}
      loading={loading}
      minWidth={1130}
      emptyTitle={t("departmentGrants.empty.title")}
      emptyDescription={t("departmentGrants.empty.description")}
    />
  );
}

interface ContentChip {
  key: string;
  label: string;
  isGroup: boolean;
}

/** 授权组徽章 + 带范围的权限徽章; 超出的收进 +N 悬浮提示, 避免行高被撑开。 */
function GrantContentCell({ policy }: { policy: DepartmentGrantPolicy }) {
  const { t } = useI18n();
  const chips: ContentChip[] = [
    ...policy.authorization_groups.map((group) => ({
      key: `group:${group.key}`,
      label: group.name,
      isGroup: true,
    })),
    ...policy.permissions.map((permission) => ({
      key: `permission:${permission.key}:${permission.scope}`,
      label: `${permission.name} · ${permission.scope_name}`,
      isGroup: false,
    })),
  ];

  if (chips.length === 0) {
    return <span className="text-ink-faint">{t("departmentGrants.content.empty")}</span>;
  }

  const visible = chips.slice(0, VISIBLE_CHIP_COUNT);
  const overflow = chips.slice(VISIBLE_CHIP_COUNT);

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {visible.map((chip) =>
        chip.isGroup ? (
          <Badge key={chip.key} tone="bond">
            {chip.label}
          </Badge>
        ) : (
          <span
            key={chip.key}
            className="inline-flex max-w-full items-center truncate rounded-[2px] border border-ink/15 bg-paper-soft px-1.5 py-0.5 text-caption leading-4 text-ink-soft"
          >
            {chip.label}
          </span>
        ),
      )}
      {overflow.length > 0 ? (
        <Tooltip
          // 键盘用户也要看得到被折叠的授权内容, 因此聚焦即展开, 而不是只在悬浮时显示。
          trigger={["hover", "focus", "click"]}
          title={
            <ul className="m-0 list-none p-0">
              {overflow.map((chip) => (
                <li key={chip.key}>{chip.label}</li>
              ))}
            </ul>
          }
        >
          <button
            type="button"
            aria-label={t("departmentGrants.content.moreLabel", { count: overflow.length })}
            className="inline-flex items-center rounded-[2px] border border-dashed border-ink/25 px-1.5 py-0.5 text-caption leading-4 text-ink-faint transition-colors hover:border-ink/45 hover:text-ink-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent/60"
          >
            {t("departmentGrants.content.more", { count: overflow.length })}
          </button>
        </Tooltip>
      ) : null}
    </div>
  );
}

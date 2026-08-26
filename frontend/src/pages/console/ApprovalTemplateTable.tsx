import { useMemo } from "react";

import { AppTable, textFilter, type ColumnsType, type ColumnType } from "../../components/antd/AppTable";
import {
  MONO_TEXT_CLASS,
  actionsColumn,
  dateTimeColumn,
  statusColumn,
  textColumn,
} from "../../components/antd/columns";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/ui/EmptyState";

import { useI18n } from "../../i18n/I18nProvider";
import type { ApprovalTemplateItem } from "../../lib/domain";
import type { Translator } from "../../lib/status";

export interface ApprovalTemplateRowActions {
  onEdit: (template: ApprovalTemplateItem) => void;
  onTest: (template: ApprovalTemplateItem) => void;
  onDelete: (template: ApprovalTemplateItem) => void;
}

export function ApprovalTemplateTable({
  templates,
  isLoading,
  actions,
}: {
  templates: ApprovalTemplateItem[];
  isLoading: boolean;
  actions: ApprovalTemplateRowActions;
}) {
  const { t } = useI18n();
  const columns = useMemo(() => templateColumns(t, actions), [actions, t]);

  return (
    <AppTable<ApprovalTemplateItem>
      columns={columns}
      dataSource={templates}
      empty={<EmptyState title={t("approvalTemplates.empty.title")} description={t("approvalTemplates.empty.description")} />}
      loading={isLoading}
      minWidth={1080}
      rowKey="id"
    />
  );
}

function templateColumns(t: Translator, actions: ApprovalTemplateRowActions): ColumnsType<ApprovalTemplateItem> {
  return [
    textColumn<ApprovalTemplateItem>({
      key: "key",
      title: t("approvalTemplates.column.key"),
      filter: true,
      sorter: true,
      mono: true,
      width: 200,
    }),
    // 名称是这张表里唯一的自由文本列, 不给固定宽度, 让它吃掉宽屏下的剩余空间。
    textColumn<ApprovalTemplateItem>({
      key: "name",
      title: t("common.name"),
      filter: true,
      sorter: true,
    }),
    appColumn(t),
    statusColumn<ApprovalTemplateItem>({
      key: "status",
      title: t("common.status"),
      getValue: (template) => (template.is_active ? "active" : "inactive"),
      options: [
        { value: "active", label: t("common.enabled"), tone: "evergreen" },
        { value: "inactive", label: t("common.disabled"), tone: "neutral" },
      ],
      width: 120,
    }),
    dateTimeColumn<ApprovalTemplateItem>({ key: "updated_at", title: t("common.updatedAt") }),
    actionsColumn<ApprovalTemplateItem>({
      title: t("common.actions"),
      width: 280,
      render: (template) => (
        <>
          <Button type="button" size="sm" variant="ghost" onClick={() => actions.onEdit(template)}>
            {t("common.edit")}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => actions.onTest(template)}>
            {t("approvalTemplates.test.action")}
          </Button>
          <Button type="button" size="sm" variant="ghost-danger" onClick={() => actions.onDelete(template)}>
            {t("common.delete")}
          </Button>
        </>
      ),
    }),
  ];
}

/**
 * 所属应用列: 有 app_key 时等宽展示, 空 app_key 是「平台共用」模板(徽章)。
 * 因为渲染有两种形态, 不能直接用 textColumn; 但表头筛选仍走共享的 textFilter,
 * 并把「平台共用」的文案也纳入匹配, 这样输入「平台」能筛出共用模板。
 */
function appColumn(t: Translator): ColumnType<ApprovalTemplateItem> {
  const sharedLabel = t("approvalTemplates.platformShared");
  const read = (template: ApprovalTemplateItem) => template.app_key || sharedLabel;

  return {
    key: "app_key",
    dataIndex: "app_key",
    title: t("approvalTemplates.column.app"),
    width: 200,
    ellipsis: true,
    render: (_value: unknown, template: ApprovalTemplateItem) =>
      template.app_key ? <code className={MONO_TEXT_CLASS}>{template.app_key}</code> : <Badge tone="bond">{sharedLabel}</Badge>,
    sorter: (a: ApprovalTemplateItem, b: ApprovalTemplateItem) => read(a).localeCompare(read(b)),
    ...textFilter<ApprovalTemplateItem>("app_key", { getValue: read }),
  };
}

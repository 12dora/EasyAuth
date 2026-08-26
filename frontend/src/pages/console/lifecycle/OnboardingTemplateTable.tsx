import { useMemo } from "react";

import { AppTable, type ColumnsType } from "../../../components/antd/AppTable";
import {
  RowActionButton,
  actionsColumn,
  dateTimeColumn,
  statusColumn,
  textColumn,
} from "../../../components/antd/columns";
import { useI18n } from "../../../i18n/I18nProvider";
import type { OnboardingTemplateRow } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";

export interface TemplateRowActions {
  onEdit: (template: OnboardingTemplateRow) => void;
  onToggle: (template: OnboardingTemplateRow) => void;
  toggling: boolean;
}

export function OnboardingTemplateTable({
  templates,
  isLoading,
  actions,
}: {
  templates: OnboardingTemplateRow[];
  isLoading: boolean;
  actions: TemplateRowActions;
}) {
  const { t } = useI18n();
  const columns = useMemo(() => templateColumns(t, actions), [actions, t]);

  return (
    // 模板接口一次返回全量, 因此分页/筛选/排序都在客户端完成。
    <AppTable<OnboardingTemplateRow>
      columns={columns}
      dataSource={templates}
      emptyDescription={t("onboarding.templates.empty.description")}
      emptyTitle={t("onboarding.templates.empty.title")}
      loading={isLoading}
      minWidth={940}
      rowKey="id"
    />
  );
}

function templateColumns(t: Translator, actions: TemplateRowActions): ColumnsType<OnboardingTemplateRow> {
  return [
    {
      key: "name",
      dataIndex: "name",
      title: t("common.name"),
      ellipsis: true,
      width: 220,
      render: (_value: unknown, template: OnboardingTemplateRow) => <strong>{template.name}</strong>,
    },
    textColumn<OnboardingTemplateRow>({ key: "description", title: t("common.description"), filter: true }),
    textColumn<OnboardingTemplateRow>({
      key: "items",
      title: t("onboarding.templates.column.items"),
      getValue: (template) => t("onboarding.templates.itemCount", { count: template.items.length }),
      width: 140,
    }),
    statusColumn<OnboardingTemplateRow>({
      key: "status",
      title: t("common.status"),
      getValue: (template) => (template.is_active ? "active" : "inactive"),
      options: [
        { value: "active", label: t("common.enabled"), tone: "evergreen" },
        { value: "inactive", label: t("common.disabled"), tone: "neutral" },
      ],
      width: 120,
    }),
    dateTimeColumn<OnboardingTemplateRow>({ key: "updated_at", title: t("common.updatedAt") }),
    actionsColumn<OnboardingTemplateRow>({
      render: (template) => (
        <>
          <RowActionButton type="button" onClick={() => actions.onEdit(template)}>
            {t("common.edit")}
          </RowActionButton>
          <RowActionButton
            type="button"
            disabled={actions.toggling}
            onClick={() => actions.onToggle(template)}
          >
            {template.is_active ? t("common.disable") : t("common.enable")}
          </RowActionButton>
        </>
      ),
    }),
  ];
}

import { Save } from "lucide-react";
import { useMemo } from "react";

import { Button } from "../../../../components/Button";
import { TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { AppTable, textFilter, type ColumnsType } from "../../../../components/antd/AppTable";
import { MONO_TEXT_CLASS } from "../../../../components/antd/columns";
import { PanelSurface } from "../../../../components/ui/PanelSurface";

import { useI18n } from "../../../../i18n/I18nProvider";
import type { AuthorizationGroupItem, ConnectorInstanceItem } from "../../../../lib/domain";
import {
  useConnectorMappings,
  type ConnectorMappingsController,
} from "./useConnectorMappings";

export function MappingsPanel({
  appKey,
  instance,
  canManage,
}: {
  appKey: string;
  instance: ConnectorInstanceItem;
  canManage: boolean;
}) {
  const { t } = useI18n();
  const controller = useConnectorMappings(appKey, instance.id);
  const { externalGroupsQuery, saveMutation } = controller;

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h3 className="text-base font-semibold text-ink">
            {t("console.connector.mappingsHeading")}
          </h3>
          <p className="max-w-3xl text-body leading-5 text-ink-soft">
            {t("console.connector.mappingsDescription")}
          </p>
        </div>
        <Button
          type="button"
          variant="primary"
          icon={<Save size={15} />}
          loading={saveMutation.isPending}
          disabled={saveMutation.isPending || !controller.authoritativeMappingsLoaded || !canManage}
          onClick={() => saveMutation.mutate()}
        >
          {t("common.save")}
        </Button>
      </div>
      {externalGroupsQuery.error ? (
        <p className="text-xs leading-5 text-ink-soft">
          {t("console.connector.externalGroupsFailed")}
        </p>
      ) : null}
      <MappingsLoadFailure controller={controller} />
      <datalist id={controller.datalistId}>
        {controller.externalGroups.map((group) => (
          <option key={group.ref} value={group.ref}>
            {group.name}
          </option>
        ))}
      </datalist>
      <MappingsTable controller={controller} canManage={canManage} />
    </PanelSurface>
  );
}

function MappingsLoadFailure({
  controller,
}: {
  controller: ConnectorMappingsController;
}) {
  const { t } = useI18n();
  const { mappingsQuery, groupsQuery } = controller;
  if (!mappingsQuery.error && !groupsQuery.error) {
    return null;
  }

  return (
    <div className="space-y-2">
      <StatusBanner live="alert"
        tone="signal"
        title={t("console.connector.loadFailed")}
        message={
          (mappingsQuery.error as Error | null)?.message ??
          (groupsQuery.error as Error).message
        }
      />
      <div>
        <Button
          type="button"
          onClick={() => {
            void mappingsQuery.refetch();
            void groupsQuery.refetch();
          }}
        >
          {t("common.retry")}
        </Button>
      </div>
    </div>
  );
}

/**
 * 授权组映射表: 整表数据在客户端(授权组一次拉全), 因此分页/筛选/排序都由
 * antd 在本地完成; 单元格里的输入框与勾选框直接改 controller 的草稿, 与分页无关。
 */
function MappingsTable({
  controller,
  canManage,
}: {
  controller: ConnectorMappingsController;
  canManage: boolean;
}) {
  const { t } = useI18n();
  const { groups } = controller;
  const columns = useMemo<ColumnsType<AuthorizationGroupItem>>(
    () => [
      {
        key: "group",
        title: t("console.connector.mappingsColumn.group"),
        width: 280,
        sorter: (left, right) => left.name.localeCompare(right.name),
        render: (_value: unknown, group: AuthorizationGroupItem) => (
          <div className="flex min-w-0 flex-col gap-1">
            <span className="truncate font-medium text-ink">{group.name}</span>
            <code className={MONO_TEXT_CLASS}>{group.key}</code>
          </div>
        ),
        ...textFilter<AuthorizationGroupItem>("group", {
          getValue: (group) => `${group.name} ${group.key}`,
        }),
      },
      {
        key: "external_ref",
        title: t("console.connector.mappingsColumn.externalRef"),
        render: (_value: unknown, group: AuthorizationGroupItem) => (
          <MappingRefInput controller={controller} group={group} canManage={canManage} />
        ),
      },
      {
        key: "auto_create",
        title: t("console.connector.mappingsColumn.autoCreate"),
        width: 200,
        render: (_value: unknown, group: AuthorizationGroupItem) => (
          <MappingAutoCreateToggle controller={controller} group={group} canManage={canManage} />
        ),
      },
    ],
    [canManage, controller, t],
  );

  return (
    <AppTable<AuthorizationGroupItem>
      columns={columns}
      dataSource={groups}
      emptyTitle={t("console.connector.mappingsEmpty")}
      rowKey="key"
    />
  );
}

function mappingDraft(controller: ConnectorMappingsController, groupKey: string) {
  return controller.drafts[groupKey] ?? { external_ref: "", auto_create: false };
}

function MappingRefInput({
  controller,
  group,
  canManage,
}: {
  controller: ConnectorMappingsController;
  group: AuthorizationGroupItem;
  canManage: boolean;
}) {
  const { t } = useI18n();
  const { datalistId, authoritativeMappingsLoaded, setDraft } = controller;
  const draft = mappingDraft(controller, group.key);

  return (
    <TextInput
      list={datalistId}
      className="max-w-72 font-mono"
      aria-label={t("console.connector.mappingsColumn.externalRef")}
      placeholder={t("console.connector.mappingsRefPlaceholder")}
      value={draft.external_ref}
      disabled={!authoritativeMappingsLoaded || !canManage}
      onChange={(event) => setDraft(group.key, { external_ref: event.currentTarget.value })}
    />
  );
}

function MappingAutoCreateToggle({
  controller,
  group,
  canManage,
}: {
  controller: ConnectorMappingsController;
  group: AuthorizationGroupItem;
  canManage: boolean;
}) {
  const { t } = useI18n();
  const { authoritativeMappingsLoaded, setDraft } = controller;
  const draft = mappingDraft(controller, group.key);

  return (
    <label className="inline-flex items-center gap-2 text-body text-ink">
      <input
        type="checkbox"
        checked={draft.auto_create}
        disabled={!authoritativeMappingsLoaded || !canManage || draft.external_ref.trim() === ""}
        onChange={(event) => setDraft(group.key, { auto_create: event.currentTarget.checked })}
      />
      <span>{t("console.connector.mappingsAutoCreateLabel")}</span>
    </label>
  );
}

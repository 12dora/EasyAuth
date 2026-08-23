import { Save } from "lucide-react";

import { Button } from "../../../../components/Button";
import { TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import {
  TableBody,
  TableCell,
  TableEmptyRow,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
} from "../../../../components/ui/TablePrimitives";
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

function MappingsTable({
  controller,
  canManage,
}: {
  controller: ConnectorMappingsController;
  canManage: boolean;
}) {
  const { t } = useI18n();
  const { groups } = controller;

  return (
    <TableFrame>
      <TableRoot>
        <TableHead>
          <TableRow>
            <TableHeaderCell>
              {t("console.connector.mappingsColumn.group")}
            </TableHeaderCell>
            <TableHeaderCell>
              {t("console.connector.mappingsColumn.externalRef")}
            </TableHeaderCell>
            <TableHeaderCell>
              {t("console.connector.mappingsColumn.autoCreate")}
            </TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {groups.length === 0 ? (
            <TableEmptyRow colSpan={3}>
              <EmptyState title={t("console.connector.mappingsEmpty")} />
            </TableEmptyRow>
          ) : (
            groups.map((group) => (
              <MappingRow
                key={group.key}
                controller={controller}
                group={group}
                canManage={canManage}
              />
            ))
          )}
        </TableBody>
      </TableRoot>
    </TableFrame>
  );
}

function MappingRow({
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
  const draft = controller.drafts[group.key] ?? {
    external_ref: "",
    auto_create: false,
  };

  return (
    <TableRow>
      <TableCell>
        <span className="font-medium text-ink">{group.name}</span>{" "}
        <code className="text-xs text-ink-faint">{group.key}</code>
      </TableCell>
      <TableCell>
        <TextInput
          list={datalistId}
          className="max-w-72 font-mono"
          aria-label={t("console.connector.mappingsColumn.externalRef")}
          placeholder={t("console.connector.mappingsRefPlaceholder")}
          value={draft.external_ref}
          disabled={!authoritativeMappingsLoaded || !canManage}
          onChange={(event) =>
            setDraft(group.key, { external_ref: event.currentTarget.value })
          }
        />
      </TableCell>
      <TableCell>
        <label className="inline-flex items-center gap-2 text-body text-ink">
          <input
            type="checkbox"
            checked={draft.auto_create}
            disabled={
              !authoritativeMappingsLoaded ||
              !canManage ||
              draft.external_ref.trim() === ""
            }
            onChange={(event) =>
              setDraft(group.key, { auto_create: event.currentTarget.checked })
            }
          />
          <span>{t("console.connector.mappingsAutoCreateLabel")}</span>
        </label>
      </TableCell>
    </TableRow>
  );
}

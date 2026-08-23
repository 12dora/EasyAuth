import { PlugZap, Save } from "lucide-react";

import { Button } from "../../../../components/Button";
import { Field, SelectInput, TextInput } from "../../../../components/Field";
import { SchemaForm } from "../../../../components/SchemaForm";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { ConnectorTypeItem } from "../../../../lib/domain";
import type { ConnectorInstanceFormController } from "./useConnectorInstanceForm";

export function ConnectorInstanceForm({
  controller,
}: {
  controller: ConnectorInstanceFormController;
}) {
  const { t } = useI18n();
  const { connectorsQuery, selection, flags } = controller;

  return (
    <form className="grid max-w-3xl gap-4" onSubmit={controller.submit}>
      <ConnectorTypeField controller={controller} />
      {selection.activeType ? (
        <>
          <ConnectorConfigFields
            controller={controller}
            activeType={selection.activeType}
          />
          {flags.saveBlockedByTest ? (
            <p className="text-xs leading-5 text-ink-soft">
              {t("console.connector.testRequiredHint")}
            </p>
          ) : null}
          <ConnectorFormActions controller={controller} />
        </>
      ) : selection.connectorTypes.length === 0 && !connectorsQuery.isLoading ? (
        <EmptyState title={t("console.connector.noTypes")} />
      ) : null}
    </form>
  );
}

function ConnectorTypeField({
  controller,
}: {
  controller: ConnectorInstanceFormController;
}) {
  const { t } = useI18n();
  const { connectorsQuery, selection, mutations, flags } = controller;

  return (
    <Field label={t("console.connector.typeLabel")}>
      <SelectInput
        value={flags.selectionValue}
        disabled={
          connectorsQuery.isLoading ||
          Boolean(connectorsQuery.error) ||
          mutations.testMutation.isPending ||
          mutations.saveMutation.isPending
        }
        onChange={(event) =>
          controller.changeSelection(event.currentTarget.value)
        }
      >
        <option value="">{t("console.connector.typePlaceholder")}</option>
        {selection.instances.map((item) => (
          <option key={`instance:${item.id}`} value={`instance:${item.id}`}>
            {item.display_name}
          </option>
        ))}
        {selection.availableTypes.map((item) => (
          <option key={`new:${item.key}`} value={`new:${item.key}`}>
            {item.display_name}
          </option>
        ))}
      </SelectInput>
    </Field>
  );
}

function ConnectorConfigFields({
  controller,
  activeType,
}: {
  controller: ConnectorInstanceFormController;
  activeType: ConnectorTypeItem;
}) {
  const { t } = useI18n();
  const { drafts, selection, mutations, flags, canManage } = controller;
  const editDisabled =
    !flags.authoritativeConfigLoaded ||
    !canManage ||
    !flags.candidateLoaded ||
    mutations.saveMutation.isPending;

  return (
    <>
      <SchemaForm
        schema={activeType.config_schema}
        value={drafts.configDraft}
        onChange={(next) => drafts.setConfigDraft(next)}
        configuredSecrets={selection.instance?.configured_secrets ?? []}
        disabled={editDisabled || mutations.testMutation.isPending}
      />
      <Field
        label={t("console.connector.intervalLabel")}
        hint={t("console.connector.intervalHint")}
      >
        <TextInput
          type="number"
          min={60}
          max={86400}
          value={drafts.intervalDraft}
          disabled={editDisabled}
          onChange={(event) => drafts.setIntervalDraft(event.currentTarget.value)}
        />
      </Field>
      <label className="inline-flex items-center gap-2 text-body text-ink">
        <input
          type="checkbox"
          checked={drafts.enabledDraft}
          disabled={editDisabled}
          onChange={(event) => drafts.setEnabledDraft(event.currentTarget.checked)}
        />
        <span>{t("console.connector.enabled")}</span>
      </label>
    </>
  );
}

function ConnectorFormActions({
  controller,
}: {
  controller: ConnectorInstanceFormController;
}) {
  const { t } = useI18n();
  const { mutations, flags } = controller;

  return (
    <div className="flex flex-wrap gap-2">
      <Button
        type="button"
        icon={<PlugZap size={15} />}
        loading={mutations.testMutation.isPending}
        disabled={mutations.testMutation.isPending || !flags.canOperate}
        onClick={controller.runTest}
      >
        {t("console.connector.test")}
      </Button>
      <Button
        type="submit"
        variant="primary"
        icon={<Save size={15} />}
        loading={mutations.saveMutation.isPending}
        disabled={
          mutations.saveMutation.isPending ||
          !flags.canOperate ||
          flags.saveBlockedByTest
        }
      >
        {t("common.save")}
      </Button>
    </div>
  );
}

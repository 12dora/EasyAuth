import type { Dispatch, FormEvent, RefObject, SetStateAction } from "react";

import { Button } from "../../../../components/Button";
import { Field, SelectInput, TextInput } from "../../../../components/Field";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppNotificationChannelPayload, DirectoryScopeItem } from "../../../../lib/domain";
import { scopeKey, type ChannelFormState } from "./notificationChannelPayload";

export function NotificationChannelForm({
  form,
  setForm,
  channel,
  availableDirectoryScopes,
  currentScopeIsAvailable,
  noAvailableScopes,
  canWriteChannel,
  isLoading,
  isSaving,
  isTesting,
  formComplete,
  secretInputRef,
  onSecretInput,
  onSubmit,
  onTest,
}: {
  form: ChannelFormState;
  setForm: Dispatch<SetStateAction<ChannelFormState>>;
  channel: AppNotificationChannelPayload["notification_channel"];
  availableDirectoryScopes: DirectoryScopeItem[];
  currentScopeIsAvailable: boolean;
  noAvailableScopes: boolean;
  canWriteChannel: boolean;
  isLoading: boolean;
  isSaving: boolean;
  isTesting: boolean;
  formComplete: boolean;
  secretInputRef: RefObject<HTMLInputElement | null>;
  onSecretInput: (hasValue: boolean) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onTest: () => void;
}) {
  const { t } = useI18n();

  return (
    <form className="grid gap-4" onSubmit={onSubmit} aria-busy={isLoading}>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("console.integration.channelName")}>
          <TextInput
            value={form.name}
            disabled={!canWriteChannel || isSaving}
            onChange={(event) => {
              const name = event.currentTarget.value;
              setForm((current) => ({ ...current, name }));
            }}
          />
        </Field>
        <Field label={t("console.integration.agentId")} hint={t("console.integration.agentIdHint")}>
          <TextInput
            className="font-mono"
            value={form.agentId}
            disabled={!canWriteChannel || isSaving}
            onChange={(event) => {
              const agentId = event.currentTarget.value;
              setForm((current) => ({ ...current, agentId }));
            }}
          />
        </Field>
        <Field label={t("console.integration.dingtalkAppKey")}>
          <TextInput
            className="font-mono"
            autoComplete="off"
            value={form.dingtalkAppKey}
            disabled={!canWriteChannel || isSaving}
            onChange={(event) => {
              const dingtalkAppKey = event.currentTarget.value;
              setForm((current) => ({ ...current, dingtalkAppKey }));
            }}
          />
        </Field>
        <Field label={t("console.integration.directoryScopeSelect")} hint={t("console.integration.directoryScopeSelectHint")}>
          <SelectInput
            className="font-mono"
            value={scopeKey(form.directorySourceSlug, form.corpId)}
            disabled={!canWriteChannel || noAvailableScopes || isSaving}
            onChange={(event) => {
              const selected = availableDirectoryScopes.find((scope) => scopeKey(scope.directory_source_slug, scope.corp_id) === event.currentTarget.value);
              if (!selected) {
                setForm((current) => ({ ...current, directorySourceSlug: "", corpId: "" }));
                return;
              }
              setForm((current) => ({
                ...current,
                directorySourceSlug: selected.directory_source_slug,
                corpId: selected.corp_id,
              }));
            }}
          >
            <option value="">{t("console.integration.directoryScopePlaceholder")}</option>
            {channel && !currentScopeIsAvailable ? (
              <option value={scopeKey(channel.directory_source_slug, channel.corp_id)} disabled>
                {t("console.integration.directoryScopeUnavailableOption", {
                  source: channel.directory_source_slug,
                  corp: channel.corp_id,
                })}
              </option>
            ) : null}
            {availableDirectoryScopes.map((scope) => (
              <option key={scopeKey(scope.directory_source_slug, scope.corp_id)} value={scopeKey(scope.directory_source_slug, scope.corp_id)}>
                {scope.directory_source_slug} / {scope.corp_id}
              </option>
            ))}
          </SelectInput>
        </Field>
        <Field
          label={t("console.integration.dingtalkAppSecret")}
          hint={channel?.app_secret_configured ? t("console.integration.secretPreserveHint") : t("console.integration.secretRequiredHint")}
        >
          <TextInput
            ref={secretInputRef}
            type="password"
            autoComplete="new-password"
            placeholder={channel?.app_secret_configured ? t("console.integration.secretConfiguredPlaceholder") : ""}
            disabled={!canWriteChannel || isSaving}
            onChange={(event) => onSecretInput(Boolean(event.currentTarget.value))}
          />
        </Field>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 pt-4">
        <p className="max-w-2xl text-xs leading-5 text-ink-faint">{t("console.integration.queueIdentityHint")}</p>
        <div className="flex gap-2">
          <Button
            type="button"
            loading={isTesting}
            disabled={!canWriteChannel || !channel || isSaving}
            onClick={onTest}
          >
            {t("console.integration.testConnectivity")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={isSaving}
            disabled={!canWriteChannel || !formComplete}
          >
            {t("console.integration.saveNewVersion")}
          </Button>
        </div>
      </div>
    </form>
  );
}

import { KeyRound, Save, Send } from "lucide-react";

import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, TextInput } from "../../../../components/Field";
import { SecretDialog } from "../../../../components/SecretDialog";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { WebhookConfigItem } from "../../../../lib/domain";
import { formatDateTime } from "../../../../lib/status";
import { TARGET_FIELDS, type WebhookTarget } from "./webhookConfig";
import type { useWebhookTab } from "./useWebhookTab";

type WebhookTabModel = ReturnType<typeof useWebhookTab>;

export function WebhookTabForm({ tab }: { tab: WebhookTabModel }) {
  const { t } = useI18n();
  const { canWrite, config, enabled, saveMutation, setEnabled, setUrls, submit, testMutation, urls } = tab;

  return (
    <form className="grid max-w-3xl gap-4" onSubmit={submit}>
      <label className="inline-flex items-center gap-2 text-body text-ink">
        <input
          type="checkbox"
          checked={enabled}
          disabled={!canWrite || saveMutation.isPending}
          onChange={(event) => setEnabled(event.currentTarget.checked)}
        />
        <span>{t("webhook.enabled")}</span>
      </label>
      {TARGET_FIELDS.map(({ target, labelKey }) => (
        <Field key={target} label={t(labelKey)}>
          <div className="flex items-center gap-2">
            <TextInput
              type="url"
              autoComplete="off"
              spellCheck={false}
              aria-label={t(labelKey)}
              className="font-mono"
              value={urls[target]}
              disabled={!canWrite || saveMutation.isPending}
              onChange={(event) => {
                const next = event.currentTarget.value;
                setUrls((current) => ({ ...current, [target]: next }));
              }}
            />
            {config?.[target] ? (
              <Button
                type="button"
                size="sm"
                icon={<Send size={14} />}
                loading={testMutation.isPending && testMutation.variables === target}
                disabled={testMutation.isPending}
                onClick={() => tab.sendTest(target)}
              >
                {t("webhook.sendTest")}
              </Button>
            ) : null}
          </div>
        </Field>
      ))}
      <WebhookFormActions config={config} tab={tab} />
    </form>
  );
}

function WebhookFormActions({ config, tab }: { config: WebhookConfigItem | null; tab: WebhookTabModel }) {
  const { t } = useI18n();
  const { canWrite, saveMutation } = tab;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs leading-5 text-ink-faint">
        {config?.updated_at
          ? t("webhook.updatedMeta", { user: config.updated_by || "-", time: formatDateTime(config.updated_at) })
          : null}
      </span>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          icon={<KeyRound size={15} />}
          loading={saveMutation.isPending}
          disabled={saveMutation.isPending || !canWrite}
          onClick={tab.requestRotate}
        >
          {t("webhook.rotate")}
        </Button>
        <Button
          type="submit"
          variant="primary"
          icon={<Save size={15} />}
          loading={saveMutation.isPending}
          disabled={saveMutation.isPending || !canWrite}
        >
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export function WebhookRotateDialog({ tab }: { tab: WebhookTabModel }) {
  const { t } = useI18n();
  const { canWrite, saveMutation, setRotateConfirmOpen } = tab;
  if (!tab.rotateConfirmOpen) {
    return null;
  }
  return (
    <Dialog
      title={t("webhook.rotateTitle")}
      size="sm"
      onClose={() => setRotateConfirmOpen(false)}
      footer={
        <>
          <Button type="button" onClick={() => setRotateConfirmOpen(false)}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="danger"
            loading={saveMutation.isPending}
            disabled={saveMutation.isPending || !canWrite}
            onClick={() => {
              if (!canWrite) {
                return;
              }
              setRotateConfirmOpen(false);
              saveMutation.mutate(true);
            }}
          >
            {t("webhook.rotateConfirm")}
          </Button>
        </>
      }
    >
      <p className="text-body leading-6 text-ink">{t("webhook.rotateMessage")}</p>
    </Dialog>
  );
}

export function WebhookSecretDialog({ tab }: { tab: WebhookTabModel }) {
  const { t } = useI18n();
  if (!tab.oneTimeSecret) {
    return null;
  }
  return (
    <SecretDialog
      title={t("webhook.secretTitle")}
      primaryLabel="secret"
      primaryValue={tab.oneTimeSecret}
      onClose={() => tab.setOneTimeSecret("")}
    />
  );
}

export type { WebhookTarget };

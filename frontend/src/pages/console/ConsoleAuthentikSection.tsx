import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Field, TextInput } from "../../components/Field";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import {
  authentikPatchBody,
  authentikStatus,
  SETTINGS_QUERY_KEY,
  SETTINGS_URL,
  sourceLabel,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";
import { SecretBadge, SettingsCard } from "./SettingsCard";

export function ConsoleAuthentikSection({ settings }: { settings: IntegrationSettingsPayload | undefined }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [baseUrl, setBaseUrl] = useState("");
  const [apiToken, setApiToken] = useState("");

  useEffect(() => {
    if (settings) {
      setBaseUrl(settings.authentik_base_url_override);
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<IntegrationSettingsPayload>(SETTINGS_URL, {
        method: "PATCH",
        body: authentikPatchBody(settings, { baseUrl, apiToken }),
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, payload);
      setApiToken("");
      toast.success(t("settings.integration.saveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("settings.integration.saveFailed"), error.message);
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    saveMutation.mutate();
  };

  return (
    <SettingsCard
      eyebrow={t("settings.eyebrow.identity")}
      title={t("settings.integration.title")}
      description={t("settings.integration.cardDescription")}
      status={settings ? authentikStatus(t, settings) : undefined}
      onSubmit={submit}
      footer={
        <Button
          type="submit"
          variant="primary"
          icon={<Save size={15} />}
          loading={saveMutation.isPending}
          disabled={saveMutation.isPending || !settings}
        >
          {t("settings.integration.save")}
        </Button>
      }
    >
      <Field label={t("settings.integration.baseUrl")} hint={t("settings.integration.baseUrlHint")}>
        <TextInput
          value={baseUrl}
          placeholder={settings?.authentik_base_url_effective ?? ""}
          onChange={(event) => setBaseUrl(event.currentTarget.value)}
        />
      </Field>
      <Field
        label={t("settings.integration.apiToken")}
        hint={t("settings.integration.apiTokenHint")}
        labelExtra={
          settings ? (
            <SecretBadge
              configured={settings.authentik_api_token_configured}
              configuredLabel={t("settings.integration.apiTokenConfigured")}
              missingLabel={t("settings.integration.apiTokenMissing")}
            />
          ) : null
        }
      >
        <TextInput
          type="password"
          autoComplete="off"
          value={apiToken}
          onChange={(event) => setApiToken(event.currentTarget.value)}
        />
      </Field>
      {settings ? <EffectiveBaseUrl settings={settings} /> : null}
    </SettingsCard>
  );
}

/** 当前生效地址来自覆盖值或环境变量, 两者都可能与输入框内容不同, 所以单列一行并标注来源。 */
function EffectiveBaseUrl({ settings }: { settings: IntegrationSettingsPayload }) {
  const { t } = useI18n();
  return (
    <div className="mt-auto border-t border-ink/10 pt-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">
          {t("settings.integration.effectiveBaseUrl")}
        </span>
        <Badge tone={settings.authentik_base_url_source === "missing" ? "signal" : "neutral"}>
          {sourceLabel(t, settings.authentik_base_url_source)}
        </Badge>
      </div>
      <code className="mt-1 block truncate text-body text-ink">{settings.authentik_base_url_effective || "-"}</code>
    </div>
  );
}

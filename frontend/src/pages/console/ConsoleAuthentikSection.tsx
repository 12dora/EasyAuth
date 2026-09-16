import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/Button";
import { Field, TextInput } from "../../components/Field";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import {
  authentikPatchBody,
  authentikStatus,
  baseUrlHint,
  effectiveBaseUrl,
  SETTINGS_QUERY_KEY,
  SETTINGS_URL,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";
import { SecretBadge, SettingsCard } from "./SettingsCard";
import { ConnectionTestControl } from "./SettingsConnectionTest";

export function ConsoleAuthentikSection({ settings }: { settings: IntegrationSettingsPayload | undefined }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [baseUrl, setBaseUrl] = useState("");
  const [apiToken, setApiToken] = useState("");

  useEffect(() => {
    if (settings) {
      // 输入框直接显示生效地址(覆盖值优先, 否则环境变量回退), 不再单列「当前生效地址」行。
      setBaseUrl(effectiveBaseUrl(settings));
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
        <>
          <ConnectionTestControl
            url={`${SETTINGS_URL}/authentik/test`}
            disabled={!settings}
            testId="authentik-connection-test"
            body={() => ({
              authentik_base_url: baseUrl.trim(),
              authentik_api_token: apiToken.trim(),
            })}
          />
          <Button
            type="submit"
            variant="primary"
            icon={<Save size={15} />}
            loading={saveMutation.isPending}
            disabled={saveMutation.isPending || !settings}
          >
            {t("settings.integration.save")}
          </Button>
        </>
      }
    >
      <Field label={t("settings.integration.baseUrl")} hint={baseUrlHint(t, settings)}>
        <TextInput value={baseUrl} onChange={(event) => setBaseUrl(event.currentTarget.value)} />
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
    </SettingsCard>
  );
}

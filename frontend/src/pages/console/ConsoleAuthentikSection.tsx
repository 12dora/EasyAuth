import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Field, TextInput } from "../../components/Field";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import {
  authentikPatchBody,
  SETTINGS_QUERY_KEY,
  SETTINGS_URL,
  sourceLabel,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";

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
    <PanelSurface padding="lg" className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("settings.integration.title")}</h2>
        {settings ? (
          <p className="flex flex-wrap items-center gap-2 text-body text-ink-soft">
            <span>
              {t("settings.integration.effectiveBaseUrl")}: <code>{settings.authentik_base_url_effective || "-"}</code>
            </span>
            <Badge tone={settings.authentik_base_url_source === "missing" ? "signal" : "neutral"}>
              {sourceLabel(t, settings.authentik_base_url_source)}
            </Badge>
          </p>
        ) : null}
      </div>
      <form className="grid gap-4" onSubmit={submit}>
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
          labelExtra={settings ? <ApiTokenBadge settings={settings} /> : null}
        >
          <TextInput
            type="password"
            autoComplete="off"
            value={apiToken}
            onChange={(event) => setApiToken(event.currentTarget.value)}
          />
        </Field>
        <div className="flex justify-end">
          <Button
            type="submit"
            variant="primary"
            icon={<Save size={15} />}
            loading={saveMutation.isPending}
            disabled={saveMutation.isPending || !settings}
          >
            {t("settings.integration.save")}
          </Button>
        </div>
      </form>
    </PanelSurface>
  );
}

function ApiTokenBadge({ settings }: { settings: IntegrationSettingsPayload }) {
  const { t } = useI18n();
  return (
    <Badge tone={settings.authentik_api_token_configured ? "evergreen" : "amber"}>
      {settings.authentik_api_token_configured
        ? `${t("settings.integration.apiTokenConfigured")} · ${sourceLabel(t, settings.authentik_api_token_source)}`
        : t("settings.integration.apiTokenMissing")}
    </Badge>
  );
}

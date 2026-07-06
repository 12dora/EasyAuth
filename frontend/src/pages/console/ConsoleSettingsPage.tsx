import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PlugZap, Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { ButtonLink } from "../../components/ButtonLink";
import { Field, TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import { TwoFactorSection } from "./TwoFactorSection";

interface IntegrationSettingsPayload {
  authentik_base_url_override: string;
  authentik_base_url_effective: string;
  authentik_base_url_source: "override" | "env" | "missing";
  authentik_api_token_configured: boolean;
  authentik_api_token_source: "override" | "env" | "missing";
  authentik_source_slug: string;
  dingtalk_app_key: string;
  dingtalk_app_secret_configured: boolean;
  dingtalk_agent_id: string;
  updated_at: string | null;
  updated_by: string;
}

interface DingtalkTestResult {
  ok: boolean;
  message: string;
}

const SETTINGS_QUERY_KEY = ["console", "settings", "integrations"];

export function ConsoleSettingsPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [baseUrl, setBaseUrl] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [saved, setSaved] = useState(false);
  const settingsQuery = useQuery({
    queryKey: SETTINGS_QUERY_KEY,
    queryFn: () => apiRequest<IntegrationSettingsPayload>("/console/api/v1/settings/integrations"),
  });
  const settings = settingsQuery.data;

  useEffect(() => {
    if (settings) {
      setBaseUrl(settings.authentik_base_url_override);
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<IntegrationSettingsPayload>("/console/api/v1/settings/integrations", {
        method: "PUT",
        body: {
          authentik_base_url: baseUrl.trim(),
          // 留空表示保持现有 token 不变。
          ...(apiToken.trim() === "" ? {} : { authentik_api_token: apiToken.trim() }),
        },
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, payload);
      setApiToken("");
      setSaved(true);
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaved(false);
    saveMutation.mutate();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={t("settingsPlaceholder.eyebrow")}
        title={t("settingsPlaceholder.console.title")}
        description={t("settings.integration.description")}
        actions={<ButtonLink to="/console/operations/dependency-health">{t("settings.integration.healthLink")}</ButtonLink>}
      />
      {settingsQuery.error ? (
        <StatusBanner tone="signal" title={t("settings.integration.loadFailed")} message={(settingsQuery.error as Error).message} />
      ) : null}
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
        <form className="grid max-w-2xl gap-4" onSubmit={submit}>
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
                <Badge tone={settings.authentik_api_token_configured ? "evergreen" : "amber"}>
                  {settings.authentik_api_token_configured
                    ? `${t("settings.integration.apiTokenConfigured")} · ${sourceLabel(t, settings.authentik_api_token_source)}`
                    : t("settings.integration.apiTokenMissing")}
                </Badge>
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
          {saveMutation.error ? (
            <StatusBanner tone="signal" title={t("settings.integration.saveFailed")} message={(saveMutation.error as Error).message} />
          ) : null}
          {saved ? <StatusBanner tone="evergreen" title={t("settings.integration.saveSuccess")} /> : null}
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
      <DingtalkIntegrationSection settings={settings} />
      <TwoFactorSection />
    </div>
  );
}

function DingtalkIntegrationSection({ settings }: { settings: IntegrationSettingsPayload | undefined }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [appKey, setAppKey] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [agentId, setAgentId] = useState("");
  const [saved, setSaved] = useState(false);
  const [testResult, setTestResult] = useState<DingtalkTestResult | null>(null);

  useEffect(() => {
    if (settings) {
      setAppKey(settings.dingtalk_app_key);
      setAgentId(settings.dingtalk_agent_id);
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: () => {
      // PUT 载荷只包含用户改动过的字段: 未动的字段省略(=保持不变), secret 留空同样省略。
      const body: JsonObject = {};
      if (settings && appKey.trim() !== settings.dingtalk_app_key) {
        body.dingtalk_app_key = appKey.trim();
      }
      if (appSecret !== "") {
        body.dingtalk_app_secret = appSecret;
      }
      if (settings && agentId.trim() !== settings.dingtalk_agent_id) {
        body.dingtalk_agent_id = agentId.trim();
      }
      return apiRequest<IntegrationSettingsPayload>("/console/api/v1/settings/integrations", {
        method: "PUT",
        body,
      });
    },
    onSuccess: (payload) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, payload);
      setAppSecret("");
      setSaved(true);
    },
  });
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<DingtalkTestResult>("/console/api/v1/settings/integrations/dingtalk/test", {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      setTestResult(payload);
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaved(false);
    setTestResult(null);
    saveMutation.mutate();
  };

  const runTest = () => {
    setSaved(false);
    setTestResult(null);
    testMutation.mutate();
  };

  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("settings.dingtalk.title")}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("settings.dingtalk.description")}</p>
      </div>
      <form className="grid max-w-2xl gap-4" onSubmit={submit}>
        <Field label={t("settings.dingtalk.appKey")}>
          <TextInput autoComplete="off" value={appKey} onChange={(event) => setAppKey(event.currentTarget.value)} />
        </Field>
        <Field
          label={t("settings.dingtalk.appSecret")}
          hint={t("settings.dingtalk.appSecretHint")}
          labelExtra={
            settings ? (
              <Badge tone={settings.dingtalk_app_secret_configured ? "evergreen" : "amber"}>
                {settings.dingtalk_app_secret_configured
                  ? t("settings.dingtalk.secretConfigured")
                  : t("settings.dingtalk.secretMissing")}
              </Badge>
            ) : null
          }
        >
          <TextInput
            type="password"
            autoComplete="off"
            value={appSecret}
            placeholder={
              settings?.dingtalk_app_secret_configured
                ? t("settings.dingtalk.secretPlaceholderConfigured")
                : t("settings.dingtalk.secretPlaceholderMissing")
            }
            onChange={(event) => setAppSecret(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("settings.dingtalk.agentId")}>
          <TextInput autoComplete="off" value={agentId} onChange={(event) => setAgentId(event.currentTarget.value)} />
        </Field>
        {saveMutation.error ? (
          <StatusBanner tone="signal" title={t("settings.integration.saveFailed")} message={(saveMutation.error as Error).message} />
        ) : null}
        {saved ? <StatusBanner tone="evergreen" title={t("settings.integration.saveSuccess")} /> : null}
        {testMutation.error ? (
          <StatusBanner tone="signal" title={t("settings.dingtalk.testFailed")} message={(testMutation.error as Error).message} />
        ) : null}
        {testResult ? (
          <div role="status">
            <StatusBanner
              tone={testResult.ok ? "evergreen" : "signal"}
              title={testResult.ok ? t("settings.dingtalk.testSuccess") : t("settings.dingtalk.testFailed")}
              message={testResult.message}
            />
          </div>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            icon={<PlugZap size={15} />}
            loading={testMutation.isPending}
            disabled={testMutation.isPending || !settings}
            onClick={runTest}
          >
            {t("settings.dingtalk.test")}
          </Button>
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

function sourceLabel(t: ReturnType<typeof useI18n>["t"], source: "override" | "env" | "missing"): string {
  if (source === "override") {
    return t("settings.integration.source.override");
  }
  if (source === "env") {
    return t("settings.integration.source.env");
  }
  return t("settings.integration.source.missing");
}

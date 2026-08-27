import { useMutation, useQueryClient } from "@tanstack/react-query";
import { PlugZap, Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Field, TextInput } from "../../components/Field";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import {
  dingtalkPatchBody,
  SETTINGS_QUERY_KEY,
  SETTINGS_URL,
  type DingtalkTestResult,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";

export function ConsoleDingtalkSection({ settings }: { settings: IntegrationSettingsPayload | undefined }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [appKey, setAppKey] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [agentId, setAgentId] = useState("");

  useEffect(() => {
    if (settings) {
      setAppKey(settings.dingtalk_app_key);
      setAgentId(settings.dingtalk_agent_id);
    }
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<IntegrationSettingsPayload>(SETTINGS_URL, {
        method: "PATCH",
        body: dingtalkPatchBody(settings, { appKey, appSecret, agentId }),
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, payload);
      setAppSecret("");
      toast.success(t("settings.integration.saveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("settings.integration.saveFailed"), error.message);
    },
  });
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<DingtalkTestResult>(`${SETTINGS_URL}/dingtalk/test`, {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      // 连接测试的结果本身就是操作反馈: ok 走成功 toast, 否则走失败 toast, 均带后端返回的说明。
      if (payload.ok) {
        toast.success(t("settings.dingtalk.testSuccess"), payload.message);
      } else {
        toast.error(t("settings.dingtalk.testFailed"), payload.message);
      }
    },
    onError: (error: Error) => {
      toast.error(t("settings.dingtalk.testFailed"), error.message);
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    saveMutation.mutate();
  };

  const runTest = () => {
    testMutation.mutate();
  };

  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("settings.dingtalk.title")}</h2>
        <p className="text-body leading-5 text-ink-soft">{t("settings.dingtalk.description")}</p>
      </div>
      <form className="grid gap-4" onSubmit={submit}>
        <Field label={t("settings.dingtalk.appKey")}>
          <TextInput autoComplete="off" value={appKey} onChange={(event) => setAppKey(event.currentTarget.value)} />
        </Field>
        <Field
          label={t("settings.dingtalk.appSecret")}
          hint={t("settings.dingtalk.appSecretHint")}
          labelExtra={settings ? <SecretBadge configured={settings.dingtalk_app_secret_configured} /> : null}
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

function SecretBadge({ configured }: { configured: boolean }) {
  const { t } = useI18n();
  return (
    <Badge tone={configured ? "evergreen" : "amber"}>
      {configured ? t("settings.dingtalk.secretConfigured") : t("settings.dingtalk.secretMissing")}
    </Badge>
  );
}

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
  type DingtalkSettingsInput,
  type DingtalkTestResult,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";

export function ConsoleDingtalkSection({ settings }: { settings: IntegrationSettingsPayload | undefined }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const form = useDingtalkFormState(settings);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<IntegrationSettingsPayload>(SETTINGS_URL, {
        method: "PATCH",
        body: dingtalkPatchBody(settings, form.values),
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(SETTINGS_QUERY_KEY, payload);
      form.clearSecrets();
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

  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("settings.dingtalk.title")}</h2>
        <p className="text-body leading-5 text-ink-soft">{t("settings.dingtalk.description")}</p>
      </div>
      <form className="grid gap-4" onSubmit={submit}>
        <DingtalkMainFields settings={settings} form={form} />
        <DingtalkNotifyFields settings={settings} form={form} />
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            type="button"
            icon={<PlugZap size={15} />}
            loading={testMutation.isPending}
            disabled={testMutation.isPending || !settings}
            onClick={() => testMutation.mutate()}
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

function DingtalkMainFields({
  settings,
  form,
}: {
  settings: IntegrationSettingsPayload | undefined;
  form: DingtalkFormState;
}) {
  const { t } = useI18n();
  return (
    <>
      <Field label={t("settings.dingtalk.appKey")}>
        <TextInput autoComplete="off" value={form.values.appKey} onChange={(event) => form.setAppKey(event.currentTarget.value)} />
      </Field>
      <Field
        label={t("settings.dingtalk.appSecret")}
        hint={t("settings.dingtalk.appSecretHint")}
        labelExtra={settings ? <SecretBadge configured={settings.dingtalk_app_secret_configured} /> : null}
      >
        <TextInput
          type="password"
          autoComplete="off"
          value={form.values.appSecret}
          placeholder={
            settings?.dingtalk_app_secret_configured
              ? t("settings.dingtalk.secretPlaceholderConfigured")
              : t("settings.dingtalk.secretPlaceholderMissing")
          }
          onChange={(event) => form.setAppSecret(event.currentTarget.value)}
        />
      </Field>
      <Field label={t("settings.dingtalk.agentId")}>
        <TextInput autoComplete="off" value={form.values.agentId} onChange={(event) => form.setAgentId(event.currentTarget.value)} />
      </Field>
    </>
  );
}

function DingtalkNotifyFields({
  settings,
  form,
}: {
  settings: IntegrationSettingsPayload | undefined;
  form: DingtalkFormState;
}) {
  const { t } = useI18n();
  return (
    <div className="grid gap-4 border-t border-ink/10 pt-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold text-ink">{t("settings.dingtalk.notifyTitle")}</h3>
        <p className="text-body leading-5 text-ink-soft">{t("settings.dingtalk.notifyHint")}</p>
      </div>
      <Field label={t("settings.dingtalk.notifyAppKey")}>
        <TextInput autoComplete="off" value={form.values.notifyAppKey} onChange={(event) => form.setNotifyAppKey(event.currentTarget.value)} />
      </Field>
      <Field
        label={t("settings.dingtalk.notifyAppSecret")}
        hint={t("settings.dingtalk.appSecretHint")}
        labelExtra={
          settings ? (
            <SecretBadge
              configured={settings.dingtalk_notify_app_secret_configured}
              configuredLabel={t("settings.dingtalk.notifySecretConfigured")}
              missingLabel={t("settings.dingtalk.notifySecretMissing")}
            />
          ) : null
        }
      >
        <TextInput
          type="password"
          autoComplete="off"
          value={form.values.notifyAppSecret}
          placeholder={
            settings?.dingtalk_notify_app_secret_configured
              ? t("settings.dingtalk.notifySecretPlaceholderConfigured")
              : t("settings.dingtalk.notifySecretPlaceholderMissing")
          }
          onChange={(event) => form.setNotifyAppSecret(event.currentTarget.value)}
        />
      </Field>
      <Field label={t("settings.dingtalk.notifyAgentId")}>
        <TextInput autoComplete="off" value={form.values.notifyAgentId} onChange={(event) => form.setNotifyAgentId(event.currentTarget.value)} />
      </Field>
    </div>
  );
}

interface DingtalkFormState {
  values: DingtalkSettingsInput;
  setAppKey: (value: string) => void;
  setAppSecret: (value: string) => void;
  setAgentId: (value: string) => void;
  setNotifyAppKey: (value: string) => void;
  setNotifyAppSecret: (value: string) => void;
  setNotifyAgentId: (value: string) => void;
  clearSecrets: () => void;
}

function useDingtalkFormState(settings: IntegrationSettingsPayload | undefined): DingtalkFormState {
  const [appKey, setAppKey] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [agentId, setAgentId] = useState("");
  const [notifyAppKey, setNotifyAppKey] = useState("");
  const [notifyAppSecret, setNotifyAppSecret] = useState("");
  const [notifyAgentId, setNotifyAgentId] = useState("");

  useEffect(() => {
    if (!settings) {
      return;
    }
    setAppKey(settings.dingtalk_app_key);
    setAgentId(settings.dingtalk_agent_id);
    setNotifyAppKey(settings.dingtalk_notify_app_key);
    setNotifyAgentId(settings.dingtalk_notify_agent_id);
  }, [settings]);

  return {
    values: { appKey, appSecret, agentId, notifyAppKey, notifyAppSecret, notifyAgentId },
    setAppKey,
    setAppSecret,
    setAgentId,
    setNotifyAppKey,
    setNotifyAppSecret,
    setNotifyAgentId,
    clearSecrets: () => {
      setAppSecret("");
      setNotifyAppSecret("");
    },
  };
}

function SecretBadge({
  configured,
  configuredLabel,
  missingLabel,
}: {
  configured: boolean;
  configuredLabel?: string;
  missingLabel?: string;
}) {
  const { t } = useI18n();
  const configuredText = configuredLabel ?? t("settings.dingtalk.secretConfigured");
  const missingText = missingLabel ?? t("settings.dingtalk.secretMissing");
  return <Badge tone={configured ? "evergreen" : "amber"}>{configured ? configuredText : missingText}</Badge>;
}

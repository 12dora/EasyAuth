import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/Button";
import { Field, TextInput } from "../../components/Field";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import {
  dingtalkAppPatchBody,
  dingtalkAppStatus,
  SETTINGS_QUERY_KEY,
  SETTINGS_URL,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";
import { SecretBadge, SettingsCard } from "./SettingsCard";
import { ConnectionTestControl } from "./SettingsConnectionTest";

/** 钉钉「统一认证应用」卡片: 目录同步、事件订阅与登录共用的主应用三元组。 */
export function ConsoleDingtalkSection({ settings }: { settings: IntegrationSettingsPayload | undefined }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [appKey, setAppKey] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [agentId, setAgentId] = useState("");

  useEffect(() => {
    if (!settings) {
      return;
    }
    setAppKey(settings.dingtalk_app_key);
    setAgentId(settings.dingtalk_agent_id);
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<IntegrationSettingsPayload>(SETTINGS_URL, {
        method: "PATCH",
        body: dingtalkAppPatchBody(settings, { appKey, appSecret, agentId }),
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

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    saveMutation.mutate();
  };

  return (
    <SettingsCard
      eyebrow={t("settings.eyebrow.dingtalk")}
      title={t("settings.dingtalk.appTitle")}
      description={t("settings.dingtalk.appDescription")}
      status={settings ? dingtalkAppStatus(t, settings) : undefined}
      onSubmit={submit}
      footer={
        <>
          <ConnectionTestControl
            url={`${SETTINGS_URL}/dingtalk/test`}
            disabled={!settings}
            testId="dingtalk-connection-test"
            body={() => ({
              dingtalk_app_key: appKey.trim(),
              dingtalk_app_secret: appSecret,
              dingtalk_agent_id: agentId.trim(),
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
      <Field label={t("settings.dingtalk.appKey")}>
        <TextInput autoComplete="off" value={appKey} onChange={(event) => setAppKey(event.currentTarget.value)} />
      </Field>
      <Field
        label={t("settings.dingtalk.appSecret")}
        hint={t("settings.dingtalk.secretHint")}
        labelExtra={
          settings ? (
            <SecretBadge
              configured={settings.dingtalk_app_secret_configured}
              configuredLabel={t("settings.dingtalk.secretSet")}
              missingLabel={t("settings.dingtalk.secretUnset")}
            />
          ) : null
        }
      >
        <TextInput
          type="password"
          autoComplete="off"
          value={appSecret}
          placeholder={
            settings?.dingtalk_app_secret_configured
              ? t("settings.dingtalk.secretPlaceholderSet")
              : t("settings.dingtalk.secretPlaceholderUnset")
          }
          onChange={(event) => setAppSecret(event.currentTarget.value)}
        />
      </Field>
      <Field label={t("settings.dingtalk.agentId")} hint={t("settings.dingtalk.agentIdHint")}>
        <TextInput autoComplete="off" value={agentId} onChange={(event) => setAgentId(event.currentTarget.value)} />
      </Field>
    </SettingsCard>
  );
}

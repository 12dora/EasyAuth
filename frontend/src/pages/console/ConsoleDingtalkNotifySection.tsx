import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../components/Button";
import { Field, TextInput } from "../../components/Field";
import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import {
  dingtalkNotifyPatchBody,
  dingtalkNotifyStatus,
  SETTINGS_QUERY_KEY,
  SETTINGS_URL,
  type IntegrationSettingsPayload,
} from "./consoleSettingsModel";
import { SecretBadge, SettingsCard, SettingsSubBlock, SettingsToggle } from "./SettingsCard";

/** 钉钉「服务号」卡片: 独立的通知应用三元组 + 通知渠道开关。 */
export function ConsoleDingtalkNotifySection({ settings }: { settings: IntegrationSettingsPayload | undefined }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [appKey, setAppKey] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [agentId, setAgentId] = useState("");
  const [workNoticeEnabled, setWorkNoticeEnabled] = useState(true);
  const [robotEnabled, setRobotEnabled] = useState(true);

  useEffect(() => {
    if (!settings) {
      return;
    }
    setAppKey(settings.dingtalk_notify_app_key);
    setAgentId(settings.dingtalk_notify_agent_id);
    setWorkNoticeEnabled(settings.dingtalk_notify_work_notice_enabled);
    setRobotEnabled(settings.dingtalk_notify_robot_enabled);
  }, [settings]);

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<IntegrationSettingsPayload>(SETTINGS_URL, {
        method: "PATCH",
        body: dingtalkNotifyPatchBody(settings, {
          appKey,
          appSecret,
          agentId,
          workNoticeEnabled,
          robotEnabled,
        }),
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
      title={t("settings.dingtalk.notifyTitle")}
      description={t("settings.dingtalk.notifyDescription")}
      status={settings ? dingtalkNotifyStatus(t, settings) : undefined}
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
      <Field label={t("settings.dingtalk.notifyAppKey")}>
        <TextInput autoComplete="off" value={appKey} onChange={(event) => setAppKey(event.currentTarget.value)} />
      </Field>
      <Field
        label={t("settings.dingtalk.notifyAppSecret")}
        hint={t("settings.dingtalk.secretHint")}
        labelExtra={
          settings ? (
            <SecretBadge
              configured={settings.dingtalk_notify_app_secret_configured}
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
            settings?.dingtalk_notify_app_secret_configured
              ? t("settings.dingtalk.secretPlaceholderSet")
              : t("settings.dingtalk.secretPlaceholderUnset")
          }
          onChange={(event) => setAppSecret(event.currentTarget.value)}
        />
      </Field>
      <Field label={t("settings.dingtalk.notifyAgentId")} hint={t("settings.dingtalk.notifyAgentIdHint")}>
        <TextInput autoComplete="off" value={agentId} onChange={(event) => setAgentId(event.currentTarget.value)} />
      </Field>
      <SettingsSubBlock title={t("settings.dingtalk.channelsTitle")} hint={t("settings.dingtalk.channelsHint")}>
        <SettingsToggle
          label={t("settings.dingtalk.workNoticeEnabled")}
          hint={t("settings.dingtalk.workNoticeHint")}
          checked={workNoticeEnabled}
          disabled={!settings}
          onChange={setWorkNoticeEnabled}
        />
        <SettingsToggle
          label={t("settings.dingtalk.robotEnabled")}
          hint={t("settings.dingtalk.robotHint")}
          checked={robotEnabled}
          disabled={!settings}
          onChange={setRobotEnabled}
        />
      </SettingsSubBlock>
    </SettingsCard>
  );
}

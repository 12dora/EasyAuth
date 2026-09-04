import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { AppKeyInput } from "../../../components/AppKeyInput";
import { Button } from "../../../components/Button";
import { Field, TextArea, TextInput } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserMultiSelect } from "../../../components/UserSelect";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import { generateAppKey } from "../../../lib/appKey";
import type { AppListPayload } from "../../../lib/domain";
import { AutoOnboardPanel } from "./AutoOnboardPanel";
import { StepFooter, StepPanel } from "./StepLayout";
import type { AppSummaryLike } from "./types";

export function BasicsStep({
  app,
  appKey,
  onContinue,
  onAutoOnboarded,
}: {
  app?: AppSummaryLike;
  appKey: string;
  onContinue: (appKey: string) => void;
  onAutoOnboarded: (appKey: string) => void;
}) {
  if (appKey) {
    return <ExistingAppSummary app={app} appKey={appKey} onContinue={onContinue} />;
  }
  return <CreateAppForm onContinue={onContinue} onAutoOnboarded={onAutoOnboarded} />;
}

function ExistingAppSummary({
  app,
  appKey,
  onContinue,
}: {
  app?: AppSummaryLike;
  appKey: string;
  onContinue: (appKey: string) => void;
}) {
  const { t } = useI18n();

  return (
    <StepPanel title={t("wizard.basics.title")} description={t("wizard.basics.description")}>
      <StatusBanner tone="evergreen" title={t("wizard.basics.existing.title")} message={t("wizard.basics.existing.description")} />
      <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
        <SummaryItem label="app_key" value={<code>{app?.app_key ?? appKey}</code>} />
        <SummaryItem label={t("common.name")} value={app ? formatAppDisplayName(app) : "-"} />
        <SummaryItem label={t("common.description")} value={app?.description || "-"} />
        <SummaryItem label={t("appList.column.owners")} value={(app?.owners ?? []).join(", ") || "-"} />
      </dl>
      <StepFooter>
        <Button variant="primary" onClick={() => onContinue(appKey)}>
          {t("common.next")}
        </Button>
      </StepFooter>
    </StepPanel>
  );
}

function CreateAppForm({
  onContinue,
  onAutoOnboarded,
}: {
  onContinue: (appKey: string) => void;
  onAutoOnboarded: (appKey: string) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [appKeyInput, setAppKeyInput] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [ownerUserIds, setOwnerUserIds] = useState<string[]>([]);
  const [developerUserIds, setDeveloperUserIds] = useState<string[]>([]);
  const createMutation = useMutation({
    mutationFn: (payload: JsonObject) =>
      apiRequest<AppListPayload>("/console/api/v1/apps", { method: "POST", body: payload }),
    onSuccess: (payload) => {
      void queryClient.invalidateQueries({ queryKey: ["console", "apps"] });
      const createdKey = payload.app?.app_key;
      if (createdKey) {
        onContinue(createdKey);
      }
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    createMutation.mutate({
      app_key: appKeyInput.trim(),
      name: name.trim(),
      description: description.trim(),
      is_active: true,
      owner_user_ids: ownerUserIds,
      developer_user_ids: developerUserIds,
    });
  };

  return (
    <StepPanel title={t("wizard.basics.title")} description={t("wizard.basics.description")}>
      <AutoOnboardPanel onAutoOnboarded={onAutoOnboarded} />
      <div className="space-y-1 border-t border-ink/10 pt-4">
        <h3 className="text-sm font-semibold text-ink">{t("wizard.auto.manualTitle")}</h3>
      </div>
      <form className="grid max-w-2xl gap-4" onSubmit={submit}>
        <Field label="app_key" hint={t("wizard.basics.appKeyHint")}>
          <AppKeyInput value={appKeyInput} onChange={setAppKeyInput} onGenerate={() => setAppKeyInput(generateAppKey(name))} required />
        </Field>
        <Field label={t("appList.createDialog.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("appList.createDialog.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        <Field label={t("appList.createDialog.ownerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect value={ownerUserIds} onChange={setOwnerUserIds} />
        </Field>
        <Field label={t("appList.createDialog.developerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect value={developerUserIds} onChange={setDeveloperUserIds} />
        </Field>
        {createMutation.error ? (
          <StatusBanner live="alert" tone="signal" title={t("wizard.basics.createFailed")} message={(createMutation.error as Error).message} />
        ) : null}
        <StepFooter>
          <Button type="submit" variant="primary" icon={<Plus size={16} />} loading={createMutation.isPending} disabled={createMutation.isPending}>
            {t("wizard.basics.createAndContinue")}
          </Button>
        </StepFooter>
      </form>
    </StepPanel>
  );
}

function SummaryItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="space-y-1">
      <dt className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">{label}</dt>
      <dd className="text-sm text-ink">{value}</dd>
    </div>
  );
}

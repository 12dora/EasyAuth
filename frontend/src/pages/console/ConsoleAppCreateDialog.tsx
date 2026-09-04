import { useState, type FormEvent } from "react";

import { AppKeyInput } from "../../components/AppKeyInput";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { UserMultiSelect } from "../../components/UserSelect";
import { useI18n } from "../../i18n/I18nProvider";
import { APP_ALIAS_MAX_LENGTH } from "../../lib/appDisplayName";
import { generateAppKey } from "../../lib/appKey";

export interface AppCreateFormPayload {
  app_key: string;
  name: string;
  /** 面向员工的别名; 留空时提交空字符串, 由后端落成「无别名」。 */
  alias: string;
  description: string;
  owner_user_ids: string[];
  developer_user_ids: string[];
}

export function ConsoleAppCreateDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: AppCreateFormPayload) => void;
}) {
  const { t } = useI18n();
  const [appKey, setAppKey] = useState("");
  const [name, setName] = useState("");
  const [alias, setAlias] = useState("");
  const [description, setDescription] = useState("");
  const [ownerUserIds, setOwnerUserIds] = useState<string[]>([]);
  const [developerUserIds, setDeveloperUserIds] = useState<string[]>([]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit({
      app_key: appKey.trim(),
      name: name.trim(),
      alias: alias.trim(),
      description: description.trim(),
      owner_user_ids: ownerUserIds,
      developer_user_ids: developerUserIds,
    });
  };

  return (
    <Dialog
      title={t("appList.createDialog.title")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="create-app-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.create")}
          </Button>
        </>
      }
    >
      <form id="create-app-form" className="grid gap-4" onSubmit={submit}>
        <Field label="app_key">
          <AppKeyInput value={appKey} onChange={setAppKey} onGenerate={() => setAppKey(generateAppKey(name))} required />
        </Field>
        <Field label={t("appList.createDialog.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("appList.createDialog.alias")} hint={t("appList.createDialog.aliasHint")}>
          <TextInput
            value={alias}
            maxLength={APP_ALIAS_MAX_LENGTH}
            placeholder={t("appList.createDialog.aliasPlaceholder")}
            onChange={(event) => setAlias(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("appList.createDialog.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        <Field label={t("appList.createDialog.ownerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect aria-label="Owner 用户 ID" value={ownerUserIds} onChange={setOwnerUserIds} />
        </Field>
        <Field label={t("appList.createDialog.developerIds")} hint={t("appList.createDialog.userIdsHint")}>
          <UserMultiSelect aria-label="Developer 用户 ID" value={developerUserIds} onChange={setDeveloperUserIds} />
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("appList.createDialog.failed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}

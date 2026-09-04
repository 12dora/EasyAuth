import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../components/Button";
import { Field, SelectInput, TextInput } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { ListPayload } from "../../../lib/api";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { AuthorizationGroupItem, PermissionItem } from "../../../lib/domain";
import {
  fetchAllSelectorApps,
  type TemplateItemDraft,
  type TemplateItemKind,
} from "./onboardingTemplateModel";

/** 模板项编辑器: 选应用 → 选授权组或权限(+范围) → 期限, 逐项添加。 */
export function TemplateItemComposer({ onAdd }: { onAdd: (item: TemplateItemDraft) => void }) {
  const { t } = useI18n();
  const [appKey, setAppKey] = useState("");
  const [kind, setKind] = useState<TemplateItemKind>("group");
  const [targetKey, setTargetKey] = useState("");
  const [scopeKey, setScopeKey] = useState("");
  const [grantType, setGrantType] = useState("permanent");
  const [durationDays, setDurationDays] = useState("30");

  const appsQuery = useQuery({
    queryKey: ["console", "apps", "selector"],
    queryFn: fetchAllSelectorApps,
  });
  const apps = appsQuery.data ?? [];

  const groupsQuery = useQuery({
    queryKey: ["console", "app", appKey, "authorization-groups"],
    queryFn: () => apiRequest<ListPayload<AuthorizationGroupItem>>(`/console/api/v1/apps/${appKey}/authorization-groups`),
    enabled: Boolean(appKey) && kind === "group",
  });
  const permissionsQuery = useQuery({
    queryKey: ["console", "app", appKey, "permissions"],
    queryFn: () => apiRequest<ListPayload<PermissionItem>>(`/console/api/v1/apps/${appKey}/permissions`),
    enabled: Boolean(appKey) && kind === "permission",
  });
  const groups = itemsFromPayload<AuthorizationGroupItem>(groupsQuery.data);
  const permissions = itemsFromPayload<PermissionItem>(permissionsQuery.data);
  const selectedPermission = permissions.find((permission) => permission.key === targetKey);
  const scopeOptions = kind === "permission" ? (selectedPermission?.supported_scopes ?? []) : [];
  const optionsError = (groupsQuery.error ?? permissionsQuery.error ?? appsQuery.error) as Error | null;

  const targetName =
    kind === "group" ? (groups.find((group) => group.key === targetKey)?.name ?? "") : (selectedPermission?.name ?? "");

  const resetTarget = () => {
    setTargetKey("");
    setScopeKey("");
  };

  const add = () => {
    if (!appKey || !targetKey) {
      return;
    }
    onAdd({
      app_key: appKey,
      kind,
      key: targetKey,
      name: targetName,
      scope_key: scopeKey,
      grant_type: grantType,
      duration_days: grantType === "timed" ? Math.max(1, Number(durationDays) || 1) : null,
    });
    resetTarget();
  };

  return (
    <div className="space-y-3 rounded-[3px] border border-dashed border-ink/20 p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("onboarding.editor.app")}>
          <SelectInput
            value={appKey}
            onChange={(event) => {
              setAppKey(event.currentTarget.value);
              resetTarget();
            }}
          >
            <option value="">{t("onboarding.editor.appPlaceholder")}</option>
            {apps.map((app) => (
              <option key={app.app_key} value={app.app_key}>
                {formatAppDisplayName(app)} ({app.app_key})
              </option>
            ))}
          </SelectInput>
        </Field>
        <Field label={t("onboarding.editor.kind")}>
          <SelectInput
            value={kind}
            onChange={(event) => {
              setKind(event.currentTarget.value as TemplateItemKind);
              resetTarget();
            }}
          >
            <option value="group">{t("onboarding.editor.kind.group")}</option>
            <option value="permission">{t("onboarding.editor.kind.permission")}</option>
          </SelectInput>
        </Field>
        <Field label={t("onboarding.editor.target")}>
          <SelectInput
            value={targetKey}
            disabled={!appKey}
            onChange={(event) => {
              setTargetKey(event.currentTarget.value);
              setScopeKey("");
            }}
          >
            <option value="">{t("onboarding.editor.targetPlaceholder")}</option>
            {kind === "group"
              ? groups.map((group) => (
                  <option key={group.key} value={group.key}>
                    {group.name} ({group.key})
                  </option>
                ))
              : permissions.map((permission) => (
                  <option key={permission.key} value={permission.key}>
                    {permission.name} ({permission.key})
                  </option>
                ))}
          </SelectInput>
        </Field>
        {kind === "permission" ? (
          <Field label={t("onboarding.editor.scope")}>
            <SelectInput value={scopeKey} disabled={!targetKey} onChange={(event) => setScopeKey(event.currentTarget.value)}>
              <option value="">{t("onboarding.editor.scopeDefault")}</option>
              {scopeOptions.map((scope) => (
                <option key={scope} value={scope}>
                  {scope}
                </option>
              ))}
            </SelectInput>
          </Field>
        ) : null}
        <Field label={t("onboarding.editor.grantType")}>
          <SelectInput value={grantType} onChange={(event) => setGrantType(event.currentTarget.value)}>
            <option value="permanent">{t("status.grantType.permanent")}</option>
            <option value="timed">{t("status.grantType.timed")}</option>
          </SelectInput>
        </Field>
        {grantType === "timed" ? (
          <Field label={t("onboarding.editor.durationDays")}>
            <TextInput
              type="number"
              min={1}
              max={3650}
              value={durationDays}
              onChange={(event) => setDurationDays(event.currentTarget.value)}
            />
          </Field>
        ) : null}
      </div>
      {optionsError ? (
        <StatusBanner live="alert" tone="signal" title={t("onboarding.editor.optionsLoadFailed")} message={optionsError.message} />
      ) : null}
      <Button type="button" icon={<Plus size={15} />} disabled={!appKey || !targetKey} onClick={add}>
        {t("onboarding.editor.addItem")}
      </Button>
    </div>
  );
}

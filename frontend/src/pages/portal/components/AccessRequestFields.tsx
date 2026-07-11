import { useMemo, useState } from "react";

import { Field, SelectInput, TextArea, TextInput } from "../../../components/Field";
import { useI18n } from "../../../i18n/I18nProvider";
import type { AccessGrantType, ApproverOption } from "../hooks/useAccessRequestForm";

interface AccessRequestFieldsProps {
  appKey: string;
  approverOptions: ApproverOption[];
  selectedApproverUserIds: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  expiresAtError: boolean;
  reason: string;
  disabled?: boolean;
  onApproverToggle: (userId: string) => void;
  onGrantTypeChange: (grantType: AccessGrantType) => void;
  onExpiresAtChange: (expiresAt: string) => void;
  onReasonChange: (reason: string) => void;
}

export function AccessRequestFields({
  appKey,
  approverOptions,
  selectedApproverUserIds,
  grantType,
  expiresAt,
  expiresAtError,
  reason,
  disabled = false,
  onApproverToggle,
  onGrantTypeChange,
  onExpiresAtChange,
  onReasonChange,
}: AccessRequestFieldsProps) {
  const { t } = useI18n();
  const nowMin = useMemo(nowLocalDatetime, []);
  return (
    <>
      <ApproverMultiSelect
        appKey={appKey}
        options={approverOptions}
        selectedUserIds={selectedApproverUserIds}
        disabled={disabled}
        onToggle={onApproverToggle}
      />
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("portal.request.grantType")}>
          <SelectInput
            value={grantType}
            disabled={disabled}
            onChange={(event) => onGrantTypeChange(event.currentTarget.value as AccessGrantType)}
          >
            <option value="permanent">{t("status.grantType.permanent")}</option>
            <option value="timed">{t("status.grantType.timed")}</option>
          </SelectInput>
        </Field>
        <Field label={t("portal.request.expiresAt")} error={expiresAtError ? t("portal.request.expiresAtInvalid") : undefined}>
          <TextInput
            type="datetime-local"
            value={expiresAt}
            min={nowMin}
            onChange={(event) => onExpiresAtChange(event.currentTarget.value)}
            disabled={disabled || grantType !== "timed"}
          />
        </Field>
      </div>
      <Field label={t("portal.request.reason")}>
        <TextArea
          rows={4}
          value={reason}
          disabled={disabled}
          onChange={(event) => onReasonChange(event.currentTarget.value)}
        />
      </Field>
    </>
  );
}

/** datetime-local 的 min: 本地时区当前时刻(YYYY-MM-DDTHH:mm)。仅约束原生选择器, 真正的未来校验在 canSubmit。 */
function nowLocalDatetime(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function ApproverMultiSelect({
  appKey,
  options,
  selectedUserIds,
  disabled = false,
  onToggle,
}: {
  appKey: string;
  options: ApproverOption[];
  selectedUserIds: string[];
  disabled?: boolean;
  onToggle: (userId: string) => void;
}) {
  const { t } = useI18n();
  const [search, setSearch] = useState("");
  const normalizedSearch = search.trim();
  const visibleOptions = useMemo(() => filterApproverOptions(options, selectedUserIds, search), [options, search, selectedUserIds]);
  const controlsDisabled = disabled || !appKey;

  return (
    <Field
      as="group"
      label={t("portal.request.approvers")}
      hint={appKey ? t("portal.request.approversSelected", { count: selectedUserIds.length }) : t("portal.request.approversNeedApp")}
    >
      <div className="flex flex-col gap-2">
        <TextInput
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          placeholder={t("portal.request.approverSearchPlaceholder")}
          aria-label={t("portal.request.approverSearchPlaceholder")}
          disabled={controlsDisabled}
        />
        <div className="max-h-40 overflow-auto rounded-[2px] border border-ink/15 bg-paper-soft p-2">
          {visibleOptions.length > 0 ? (
            <div className="flex flex-col gap-1.5">
              {visibleOptions.map((option) => (
                <label key={option.user_id} className="inline-flex items-center gap-2 rounded-[2px] px-2 py-1.5 text-body text-ink-soft hover:bg-ink/5">
                  <input
                    type="checkbox"
                    checked={selectedUserIds.includes(option.user_id)}
                    onChange={() => onToggle(option.user_id)}
                    disabled={controlsDisabled}
                    aria-label={t("portal.request.approverSelect", { userId: option.user_id })}
                  />
                  <span className="text-ink">{approverOptionLabel(option, t("portal.request.approverUnnamed"))}</span>
                  {option.department ? <span className="text-ink-faint">· {option.department}</span> : null}
                </label>
              ))}
            </div>
          ) : (
            <span className="block px-2 py-1.5 text-body text-ink-faint">
              {normalizedSearch ? t("portal.request.approverNoMatch") : t("portal.request.approverSearchHint")}
            </span>
          )}
        </div>
      </div>
    </Field>
  );
}

function filterApproverOptions(options: ApproverOption[], selectedUserIds: string[], search: string): ApproverOption[] {
  const optionsById = new Map(options.map((option) => [option.user_id, option]));
  for (const userId of selectedUserIds) {
    if (!optionsById.has(userId)) {
      optionsById.set(userId, { user_id: userId });
    }
  }
  const normalizedSearch = search.trim().toLowerCase();
  if (!normalizedSearch) {
    return selectedUserIds.map((userId) => optionsById.get(userId) ?? { user_id: userId });
  }
  return Array.from(optionsById.values()).filter((option) => {
    return approverSearchText(option).includes(normalizedSearch);
  });
}

function approverOptionLabel(option: ApproverOption, fallback: string): string {
  return option.name ?? option.display_name ?? option.label ?? fallback;
}

function approverSearchText(option: ApproverOption): string {
  return [
    option.name,
    option.display_name,
    option.label,
    option.user_id,
    option.email,
    option.department,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

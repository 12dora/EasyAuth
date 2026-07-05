import { useMemo, useState } from "react";

import { Field, SelectInput, TextArea, TextInput } from "../../../components/Field";
import type { AccessGrantType, ApproverOption } from "../hooks/useAccessRequestForm";

interface AccessRequestFieldsProps {
  appKey: string;
  approverOptions: ApproverOption[];
  selectedApproverUserIds: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  expiresAtError: boolean;
  reason: string;
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
  onApproverToggle,
  onGrantTypeChange,
  onExpiresAtChange,
  onReasonChange,
}: AccessRequestFieldsProps) {
  const nowMin = useMemo(nowLocalDatetime, []);
  return (
    <>
      <ApproverMultiSelect
        appKey={appKey}
        options={approverOptions}
        selectedUserIds={selectedApproverUserIds}
        onToggle={onApproverToggle}
      />
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="授权期限">
          <SelectInput value={grantType} onChange={(event) => onGrantTypeChange(event.currentTarget.value as AccessGrantType)}>
            <option value="permanent">长期</option>
            <option value="timed">限时</option>
          </SelectInput>
        </Field>
        <Field label="过期时间" error={expiresAtError ? "过期时间必须晚于当前时间。" : undefined}>
          <TextInput
            type="datetime-local"
            value={expiresAt}
            min={nowMin}
            onChange={(event) => onExpiresAtChange(event.currentTarget.value)}
            disabled={grantType !== "timed"}
          />
        </Field>
      </div>
      <Field label="申请原因">
        <TextArea rows={4} value={reason} onChange={(event) => onReasonChange(event.currentTarget.value)} />
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
  onToggle,
}: {
  appKey: string;
  options: ApproverOption[];
  selectedUserIds: string[];
  onToggle: (userId: string) => void;
}) {
  const [search, setSearch] = useState("");
  const normalizedSearch = search.trim();
  const visibleOptions = useMemo(() => filterApproverOptions(options, selectedUserIds, search), [options, search, selectedUserIds]);

  return (
    <Field as="group" label="审批人" hint={appKey ? `已选 ${selectedUserIds.length} 名审批人。` : "请先选择应用后再选择审批人。"}>
      <div className="flex flex-col gap-2">
        <TextInput
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          placeholder="搜索审批人"
          aria-label="搜索审批人"
          disabled={!appKey}
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
                    disabled={!appKey}
                    aria-label={`选择审批人 ${option.user_id}`}
                  />
                  <span className="text-ink">{approverOptionLabel(option)}</span>
                  {option.department ? <span className="text-ink-faint">· {option.department}</span> : null}
                </label>
              ))}
            </div>
          ) : (
            <span className="block px-2 py-1.5 text-body text-ink-faint">
              {normalizedSearch ? "没有匹配的审批人" : "输入姓名、用户 ID、邮箱或部门搜索审批人"}
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

function approverOptionLabel(option: ApproverOption): string {
  return option.name ?? option.display_name ?? option.label ?? "未命名审批人";
}

function approverSearchText(option: ApproverOption): string {
  return [
    approverOptionLabel(option),
    option.user_id,
    option.email,
    option.department,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

import { X } from "lucide-react";
import { useId, useState } from "react";
import type { ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { TextInput } from "./Field";
import { UserOptionList, useUserCombobox } from "./UserCombobox";
import type { UserOption, UserSearchPurpose } from "./UserCombobox";

export type { UserOption } from "./UserCombobox";

interface UserSearchInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  "aria-label"?: string;
  "aria-describedby"?: string;
}

/** 单个用户 ID 输入: 聚焦即拉取候选, 支持按姓名/邮箱/ID 模糊搜索, 也允许直接输入 ID。 */
export function UserSearchInput({ id, value, onChange, placeholder, required, ...aria }: UserSearchInputProps) {
  const { t } = useI18n();
  const generatedId = useId();
  const listId = `${id ?? generatedId}-listbox`;
  const { open, setOpen, options, optionsQuery, highlightIndex, activeOption, containerRef, onKeyDown, pick } = useUserCombobox({
    query: value.trim(),
    purpose: "employee",
    navigateWhenClosed: false,
    openOnArrowDown: false,
    closeOnPick: true,
    onPick: (option) => onChange(option.user_id),
  });
  const getOptionId = (option: UserOption) => `${listId}-option-${encodeURIComponent(option.user_id)}`;

  return (
    <div className="relative" ref={containerRef}>
      <TextInput
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-activedescendant={activeOption ? getOptionId(activeOption) : undefined}
        autoComplete="off"
        required={required}
        placeholder={placeholder ?? t("userSelect.searchPlaceholder")}
        value={value}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.currentTarget.value);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
        {...aria}
      />
      {open ? (
        <UserOptionList
          listId={listId}
          options={options}
          isLoading={optionsQuery.isLoading || optionsQuery.isFetching}
          error={optionsQuery.error as Error | null}
          highlightIndex={highlightIndex}
          getOptionId={getOptionId}
          onPick={pick}
          onRetry={() => void optionsQuery.refetch()}
        />
      ) : null}
    </div>
  );
}

interface UserMultiSelectProps {
  id?: string;
  value: string[];
  onChange: (value: string[]) => void;
  placeholder?: string;
  "aria-label"?: string;
  "aria-describedby"?: string;
  /** 审批人选择可包含本地紧急管理账号；其他员工选择保持排除。 */
  searchPurpose?: UserSearchPurpose;
}

/** 多个用户 ID 选择: 模糊搜索加入, 已选用户以 chip 展示, 也允许回车录入手输 ID。 */
export function UserMultiSelect({ id, value, onChange, placeholder, searchPurpose = "employee", ...aria }: UserMultiSelectProps) {
  const { t } = useI18n();
  const generatedId = useId();
  const listId = `${id ?? generatedId}-listbox`;
  const [inputValue, setInputValue] = useState("");
  const add = (raw: string) => {
    // 手输内容沿用逗号/换行分隔语义, 与字段提示保持一致。
    const ids = raw
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    const fresh = [...new Set(ids)].filter((id) => !value.includes(id));
    if (fresh.length === 0) {
      if (ids.length > 0) {
        setInputValue("");
      }
      return;
    }
    onChange([...value, ...fresh]);
    setInputValue("");
  };

  const remove = (userId: string) => {
    onChange(value.filter((item) => item !== userId));
  };
  const { open, setOpen, options, optionsQuery, highlightIndex, activeOption, containerRef, onKeyDown, pick } = useUserCombobox({
    query: inputValue.trim(),
    purpose: searchPurpose,
    excludedUserIds: value,
    navigateWhenClosed: true,
    openOnArrowDown: true,
    closeOnPick: false,
    onPick: (option) => add(option.user_id),
    onEnterWithoutOption: () => add(inputValue),
    onEmptyBackspace: inputValue === "" && value.length > 0 ? () => remove(value[value.length - 1]) : undefined,
  });
  const getOptionId = (option: UserOption) => `${listId}-option-${encodeURIComponent(option.user_id)}`;

  return (
    <div className="relative" ref={containerRef}>
      <div className="flex flex-wrap items-center gap-1.5">
        {value.map((userId) => (
          <UserChip key={userId} onRemove={() => remove(userId)} removeLabel={t("userSelect.remove", { id: userId })}>
            {userId}
          </UserChip>
        ))}
      </div>
      <TextInput
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-activedescendant={activeOption ? getOptionId(activeOption) : undefined}
        autoComplete="off"
        className={value.length > 0 ? "mt-1.5" : undefined}
        placeholder={placeholder ?? t("userSelect.searchPlaceholder")}
        value={inputValue}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setInputValue(event.currentTarget.value);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => {
          // 失焦时提交未回车的手输 ID, 避免表单提交静默丢失输入。
          add(inputValue);
        }}
        {...aria}
      />
      {open ? (
        <UserOptionList
          listId={listId}
          options={options}
          isLoading={optionsQuery.isLoading || optionsQuery.isFetching}
          error={optionsQuery.error as Error | null}
          highlightIndex={highlightIndex}
          getOptionId={getOptionId}
          onPick={pick}
          onRetry={() => void optionsQuery.refetch()}
        />
      ) : null}
    </div>
  );
}

function UserChip({
  children,
  onRemove,
  removeLabel,
}: {
  children: ReactNode;
  onRemove: () => void;
  removeLabel: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-[2px] border border-ink/12 bg-paper-deep px-1.5 py-0.5 text-xs text-ink">
      <code>{children}</code>
      <button
        type="button"
        aria-label={removeLabel}
        className="inline-flex min-h-6 min-w-6 items-center justify-center text-ink-faint transition-colors hover:text-signal"
        onClick={onRemove}
      >
        <X size={12} aria-hidden="true" />
      </button>
    </span>
  );
}

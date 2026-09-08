import { X } from "lucide-react";
import { useId, useState } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { TextInput } from "./Field";
import { UserOptionList, useUserCombobox, useUserOptionsByIds, userOptionName } from "./UserCombobox";
import type { UserOption, UserSearchPurpose } from "./UserCombobox";

export type { UserOption } from "./UserCombobox";

interface UserSearchInputProps {
  id?: string;
  /** 提交值: 用户 ID。选中候选后输入框显示的是姓名, 这一份始终是 ID。 */
  value: string;
  onChange: (value: string) => void;
  /**
   * 从候选列表里选中某个用户时额外回调完整候选项。
   *
   * 输入框的值是用户 ID(允许手输), 调用方要展示"姓名 · 部门"就必须拿到这一份候选项;
   * 手输 ID 不会触发它, 因为那时并没有可信的姓名。
   */
  onSelectOption?: (option: UserOption) => void;
  /**
   * 当前选中的候选项: 有它(且与 value 同一个人)时输入框显示姓名, 部门与 ID 落到次要行。
   *
   * 调用方手输 ID 时应传 null —— 那时没有可信姓名, 只能原样显示 ID。
   */
  selectedOption?: UserOption | null;
  placeholder?: string;
  required?: boolean;
  "aria-label"?: string;
  "aria-describedby"?: string;
}

/** 单个用户 ID 输入: 聚焦即拉取候选, 支持按姓名/邮箱/ID 模糊搜索, 也允许直接输入 ID。 */
export function UserSearchInput({
  id,
  value,
  onChange,
  onSelectOption,
  selectedOption = null,
  placeholder,
  required,
  ...aria
}: UserSearchInputProps) {
  const { t } = useI18n();
  const generatedId = useId();
  const listId = `${id ?? generatedId}-listbox`;
  // 选中的人用姓名展示: 让管理员对着一串 UUID 核对被授权人是谁是不可接受的。
  const selected = selectedOption && selectedOption.user_id === value ? selectedOption : null;
  const inputValue = selected ? userOptionName(selected) : value;
  const { open, setOpen, options, optionsQuery, highlightIndex, activeOption, containerRef, onKeyDown, pick } = useUserCombobox({
    query: inputValue.trim(),
    purpose: "employee",
    navigateWhenClosed: false,
    openOnArrowDown: false,
    closeOnPick: true,
    onPick: (option) => {
      onChange(option.user_id);
      onSelectOption?.(option);
    },
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
        value={inputValue}
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
      {selected ? (
        <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs leading-5 text-ink-faint">
          {selected.department ? <span>{selected.department}</span> : null}
          <code>{selected.user_id}</code>
        </p>
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
  /**
   * 选中那一刻拿到的候选项。
   *
   * 只用来盖住"刚选完、批量解析还没回来"这一小段空窗: 真正的姓名以搜索结果和批量解析为准,
   * 移除某个人时这里也要跟着丢掉, 否则调用方再回填同一个 ID 会显示一份过期的姓名。
   */
  const [pickedOptions, setPickedOptions] = useState<Record<string, UserOption>>({});
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
    setPickedOptions((current) => {
      if (!(userId in current)) {
        return current;
      }
      const next = { ...current };
      delete next[userId];
      return next;
    });
    onChange(value.filter((item) => item !== userId));
  };
  const { open, setOpen, options, optionsQuery, highlightIndex, activeOption, containerRef, onKeyDown, pick } = useUserCombobox({
    query: inputValue.trim(),
    purpose: searchPurpose,
    excludedUserIds: value,
    navigateWhenClosed: true,
    openOnArrowDown: true,
    closeOnPick: false,
    onPick: (option) => {
      setPickedOptions((current) => ({ ...current, [option.user_id]: option }));
      add(option.user_id);
    },
    onEnterWithoutOption: () => add(inputValue),
    onEmptyBackspace: inputValue === "" && value.length > 0 ? () => remove(value[value.length - 1]) : undefined,
  });
  const getOptionId = (option: UserOption) => `${listId}-option-${encodeURIComponent(option.user_id)}`;
  // 当前搜索结果里已经有的人不必再问一次后端; 其余(调用方回填或手输的)ID 一次批量解析。
  const searchOptionsByUserId = optionsByUserId(optionsQuery.data ?? []);
  const lookupQuery = useUserOptionsByIds(
    value.filter((userId) => !(userId in searchOptionsByUserId)),
    searchPurpose,
  );
  // 越新的来源优先: 搜索结果 > 批量解析 > 选中时的快照。
  const nameSourceByUserId: Record<string, UserOption> = {
    ...pickedOptions,
    ...optionsByUserId(lookupQuery.data ?? []),
    ...searchOptionsByUserId,
  };

  return (
    <div className="relative" ref={containerRef}>
      <div className="flex flex-wrap items-center gap-1.5">
        {value.map((userId) => {
          // 姓名还没解析出来(查询在飞行中, 或目录镜像本就没有姓名)就显示 ID: 不编一个占位姓名。
          const label = userOptionName(nameSourceByUserId[userId], userId);
          return (
            <UserChip
              key={userId}
              label={label}
              isUserId={label === userId}
              onRemove={() => remove(userId)}
              removeLabel={t("userSelect.remove", { name: label })}
            />
          );
        })}
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

function optionsByUserId(options: UserOption[]): Record<string, UserOption> {
  return Object.fromEntries(options.map((option) => [option.user_id, option]));
}

function UserChip({
  label,
  isUserId,
  onRemove,
  removeLabel,
}: {
  label: string;
  /** 显示的是 ID 而不是姓名时用等宽字体, 让"没有姓名"一眼可辨。 */
  isUserId: boolean;
  onRemove: () => void;
  removeLabel: string;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-[2px] border border-ink/12 bg-paper-deep px-1.5 py-0.5 text-xs text-ink">
      {isUserId ? <code>{label}</code> : <span>{label}</span>}
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

import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../lib/api";
import type { ListPayload } from "../lib/api";
import { cn } from "../lib/cn";
import { TextInput } from "./Field";

export interface UserOption {
  user_id: string;
  name: string;
  email: string;
  department: string;
}

const OPTION_BASE_CLASS =
  "flex w-full cursor-pointer flex-col items-start gap-0.5 rounded-[2px] px-2.5 py-1.5 text-left transition-colors";

function useUserOptions(query: string, enabled: boolean) {
  const [debouncedQuery, setDebouncedQuery] = useState(query);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  return useQuery({
    queryKey: ["console", "user-search", debouncedQuery],
    queryFn: () =>
      apiRequest<ListPayload<UserOption>>(
        `/console/api/v1/users?q=${encodeURIComponent(debouncedQuery)}`,
      ),
    enabled,
    select: (payload) => itemsFromPayload<UserOption>(payload),
    placeholderData: (previous) => previous,
  });
}

function useCloseOnOutsidePointerDown(onClose: () => void) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeOnOutsidePointerDown(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("pointerdown", closeOnOutsidePointerDown);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointerDown);
  }, [onClose]);

  return containerRef;
}

function OptionList({
  options,
  isLoading,
  highlightIndex,
  onPick,
}: {
  options: UserOption[];
  isLoading: boolean;
  highlightIndex: number;
  onPick: (option: UserOption) => void;
}) {
  const { t } = useI18n();

  return (
    <div
      role="listbox"
      className="absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-y-auto rounded-[3px] border border-ink/12 bg-paper p-1 shadow-lg"
    >
      {isLoading && options.length === 0 ? (
        <p className="px-2.5 py-1.5 text-body text-ink-faint">{t("userSelect.loading")}</p>
      ) : null}
      {!isLoading && options.length === 0 ? (
        <p className="px-2.5 py-1.5 text-body text-ink-faint">{t("userSelect.empty")}</p>
      ) : null}
      {options.map((option, index) => (
        <button
          key={option.user_id}
          type="button"
          role="option"
          aria-selected={index === highlightIndex}
          className={cn(
            OPTION_BASE_CLASS,
            index === highlightIndex ? "bg-paper-deep text-ink" : "text-ink-soft hover:bg-paper-deep hover:text-ink",
          )}
          onPointerDown={(event) => {
            event.preventDefault();
            onPick(option);
          }}
        >
          <span className="text-body font-medium">{option.name || option.user_id}</span>
          <span className="flex flex-wrap items-center gap-x-2 text-xs text-ink-faint">
            <code>{option.user_id}</code>
            {option.email ? <span>{option.email}</span> : null}
            {option.department ? <span>{option.department}</span> : null}
          </span>
        </button>
      ))}
    </div>
  );
}

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
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useCloseOnOutsidePointerDown(() => setOpen(false));
  const optionsQuery = useUserOptions(value.trim(), open);
  const options = useMemo(() => optionsQuery.data ?? [], [optionsQuery.data]);

  useEffect(() => {
    setHighlightIndex(0);
  }, [options]);

  const pick = (option: UserOption) => {
    onChange(option.user_id);
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightIndex((index) => Math.min(index + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && options[highlightIndex]) {
      event.preventDefault();
      pick(options[highlightIndex]);
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <TextInput
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
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
        <OptionList
          options={options}
          isLoading={optionsQuery.isLoading || optionsQuery.isFetching}
          highlightIndex={highlightIndex}
          onPick={pick}
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
}

/** 多个用户 ID 选择: 模糊搜索加入, 已选用户以 chip 展示, 也允许回车录入手输 ID。 */
export function UserMultiSelect({ id, value, onChange, placeholder, ...aria }: UserMultiSelectProps) {
  const { t } = useI18n();
  const [inputValue, setInputValue] = useState("");
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useCloseOnOutsidePointerDown(() => setOpen(false));
  const optionsQuery = useUserOptions(inputValue.trim(), open);
  const options = useMemo(
    () => (optionsQuery.data ?? []).filter((option) => !value.includes(option.user_id)),
    [optionsQuery.data, value],
  );

  useEffect(() => {
    setHighlightIndex(0);
  }, [options]);

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

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "Backspace" && inputValue === "" && value.length > 0) {
      remove(value[value.length - 1]);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setHighlightIndex((index) => Math.min(index + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      const highlighted = open ? options[highlightIndex] : undefined;
      if (highlighted) {
        add(highlighted.user_id);
      } else {
        add(inputValue);
      }
    }
  };

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
        <OptionList
          options={options}
          isLoading={optionsQuery.isLoading || optionsQuery.isFetching}
          highlightIndex={highlightIndex}
          onPick={(option) => add(option.user_id)}
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
        className="inline-flex items-center text-ink-faint transition-colors hover:text-signal"
        onClick={onRemove}
      >
        <X size={12} aria-hidden="true" />
      </button>
    </span>
  );
}

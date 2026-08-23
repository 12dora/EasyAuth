/** 用户选择框共用的键盘导航与候选列表。 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../lib/api";
import type { ListPayload } from "../lib/api";
import { cn } from "../lib/cn";

export interface UserOption {
  user_id: string;
  name: string;
}

export type UserSearchPurpose = "employee" | "approver";

const OPTION_BASE_CLASS =
  "flex w-full cursor-pointer flex-col items-start gap-0.5 rounded-[2px] px-2.5 py-1.5 text-left transition-colors";

interface UserComboboxOptions {
  query: string;
  purpose: UserSearchPurpose;
  excludedUserIds?: string[];
  navigateWhenClosed: boolean;
  openOnArrowDown: boolean;
  closeOnPick: boolean;
  onPick: (option: UserOption) => void;
  onEnterWithoutOption?: () => void;
  onEmptyBackspace?: () => void;
}

export function useUserCombobox({
  query,
  purpose,
  excludedUserIds = EMPTY_USER_IDS,
  navigateWhenClosed,
  openOnArrowDown,
  closeOnPick,
  onPick,
  onEnterWithoutOption,
  onEmptyBackspace,
}: UserComboboxOptions) {
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const containerRef = useCloseOnOutsidePointerDown(() => setOpen(false));
  const optionsQuery = useUserOptions(query, open, purpose);
  const options = useMemo(
    () => (optionsQuery.data ?? []).filter((option) => !excludedUserIds.includes(option.user_id)),
    [excludedUserIds, optionsQuery.data],
  );

  useEffect(() => {
    setHighlightIndex(0);
  }, [options]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "Backspace" && onEmptyBackspace) {
      onEmptyBackspace();
      return;
    }
    if (!open && !navigateWhenClosed) {
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (openOnArrowDown) {
        setOpen(true);
      }
      setHighlightIndex((index) => Math.min(index + 1, options.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      const highlighted = open ? options[highlightIndex] : undefined;
      if (highlighted || onEnterWithoutOption) {
        event.preventDefault();
        if (highlighted) {
          pick(highlighted);
        } else {
          onEnterWithoutOption?.();
        }
      }
    }
  };

  const pick = (option: UserOption) => {
    onPick(option);
    if (closeOnPick) {
      setOpen(false);
    }
  };

  return {
    open,
    setOpen,
    options,
    optionsQuery,
    highlightIndex,
    activeOption: open ? options[highlightIndex] : undefined,
    containerRef,
    onKeyDown,
    pick,
  };
}

const EMPTY_USER_IDS: string[] = [];

function useUserOptions(query: string, enabled: boolean, purpose: UserSearchPurpose) {
  const [debouncedQuery, setDebouncedQuery] = useState(query);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  return useQuery({
    queryKey: ["console", "user-search", purpose, debouncedQuery],
    queryFn: () =>
      apiRequest<ListPayload<UserOption>>(
        `/console/api/v1/user-options?q=${encodeURIComponent(debouncedQuery)}&purpose=${purpose}`,
      ),
    enabled: enabled && debouncedQuery !== "",
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

export function UserOptionList({
  listId,
  options,
  isLoading,
  error,
  highlightIndex,
  getOptionId,
  onPick,
  onRetry,
}: {
  listId: string;
  options: UserOption[];
  isLoading: boolean;
  error: Error | null;
  highlightIndex: number;
  getOptionId: (option: UserOption) => string;
  onPick: (option: UserOption) => void;
  onRetry: () => void;
}) {
  const { t } = useI18n();

  return (
    <div
      id={listId}
      role="listbox"
      className="absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-y-auto rounded-[3px] border border-ink/12 bg-paper p-1 shadow-lg"
    >
      {error ? (
        <div className="space-y-1 px-2.5 py-1.5 text-body text-signal">
          <p>{t("userSelect.loadFailed")}</p>
          <button
            type="button"
            className="text-xs font-semibold underline"
            onPointerDown={(event) => event.preventDefault()}
            onClick={onRetry}
          >
            {t("common.retry")}
          </button>
        </div>
      ) : null}
      {!error && isLoading && options.length === 0 ? (
        <p className="px-2.5 py-1.5 text-body text-ink-faint">{t("userSelect.loading")}</p>
      ) : null}
      {!error && !isLoading && options.length === 0 ? (
        <p className="px-2.5 py-1.5 text-body text-ink-faint">{t("userSelect.empty")}</p>
      ) : null}
      {!error
        ? options.map((option, index) => (
            <UserOptionRow
              key={option.user_id}
              option={option}
              optionId={getOptionId(option)}
              highlighted={index === highlightIndex}
              onPick={onPick}
            />
          ))
        : null}
    </div>
  );
}

function UserOptionRow({
  option,
  optionId,
  highlighted,
  onPick,
}: {
  option: UserOption;
  optionId: string;
  highlighted: boolean;
  onPick: (option: UserOption) => void;
}) {
  return (
    <div
      id={optionId}
      role="option"
      aria-selected={highlighted}
      className={cn(
        OPTION_BASE_CLASS,
        highlighted ? "bg-paper-deep text-ink" : "text-ink-soft hover:bg-paper-deep hover:text-ink",
      )}
      onPointerDown={(event) => {
        event.preventDefault();
        onPick(option);
      }}
    >
      <span className="text-body font-medium">{option.name || option.user_id}</span>
      <span className="flex flex-wrap items-center gap-x-2 text-xs text-ink-faint">
        <code>{option.user_id}</code>
      </span>
    </div>
  );
}

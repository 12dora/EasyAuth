import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { TextInput } from "../../components/Field";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { cn } from "../../lib/cn";
import type { HandoverCandidate, HandoverUserRef } from "../../lib/domain";
import { handoverCandidatesUrl, type HandoverSurface } from "./surface";

const OPTION_BASE_CLASS =
  "flex w-full cursor-pointer flex-col items-start gap-0.5 rounded-[2px] px-2.5 py-1.5 text-left transition-colors";

export interface HandoverUserPickerProps {
  surface: HandoverSurface;
  taskId: number | string;
  value: HandoverUserRef | null;
  onChange: (user: HandoverUserRef | null) => void;
  disabled?: boolean;
  placeholder?: string;
  "aria-label"?: string;
  id?: string;
}

export function HandoverUserPicker({
  surface,
  taskId,
  value,
  onChange,
  disabled = false,
  placeholder,
  id,
  ...aria
}: HandoverUserPickerProps) {
  const { t } = useI18n();
  const generatedId = useId();
  const listId = `${id ?? generatedId}-listbox`;
  const [inputValue, setInputValue] = useState(value?.name ?? "");
  const [open, setOpen] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setInputValue(value?.name ?? "");
  }, [value?.name, value?.user_id]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(inputValue.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [inputValue]);

  useEffect(() => {
    function closeOnOutside(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, []);

  const optionsQuery = useQuery({
    queryKey: ["handover", "candidates", surface, String(taskId), debouncedQuery],
    queryFn: async () => {
      const payload = await apiRequest<{ items: HandoverCandidate[] }>(
        handoverCandidatesUrl(surface, taskId, debouncedQuery),
      );
      return payload.items ?? [];
    },
    enabled: open && !disabled,
    placeholderData: (previous) => previous,
  });
  const options = useMemo(() => optionsQuery.data ?? [], [optionsQuery.data]);

  useEffect(() => {
    setHighlightIndex(0);
  }, [options]);

  const pick = (option: HandoverCandidate) => {
    onChange({
      user_id: option.user_id,
      name: option.name,
      department: option.department,
    });
    setInputValue(option.name);
    setOpen(false);
  };

  const clear = () => {
    onChange(null);
    setInputValue("");
  };

  const activeOption = open ? options[highlightIndex] : undefined;
  const getOptionId = (option: HandoverCandidate) => `${listId}-option-${encodeURIComponent(option.user_id)}`;

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
      setHighlightIndex((index) => Math.min(index + 1, Math.max(options.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && options[highlightIndex]) {
      event.preventDefault();
      pick(options[highlightIndex]);
    }
  };

  return (
    <div className="relative min-w-40" ref={containerRef}>
      <div className="flex items-center gap-1">
        <TextInput
          id={id}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          aria-controls={listId}
          aria-activedescendant={activeOption ? getOptionId(activeOption) : undefined}
          autoComplete="off"
          disabled={disabled}
          placeholder={placeholder ?? t("handover.userPicker.placeholder")}
          value={inputValue}
          onFocus={() => {
            if (!disabled) {
              setOpen(true);
            }
          }}
          onChange={(event) => {
            setInputValue(event.currentTarget.value);
            if (value) {
              onChange(null);
            }
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
          {...aria}
        />
        {value ? (
          <button
            type="button"
            className="shrink-0 text-caption text-ink-faint underline disabled:opacity-50"
            disabled={disabled}
            onClick={clear}
          >
            {t("common.close")}
          </button>
        ) : null}
      </div>
      {open && !disabled ? (
        <div
          id={listId}
          role="listbox"
          className="absolute left-0 right-0 top-full z-30 mt-1 max-h-64 overflow-y-auto rounded-[3px] border border-ink/12 bg-paper p-1 shadow-lg"
        >
          {optionsQuery.error ? (
            <p className="px-2.5 py-1.5 text-body text-signal">{(optionsQuery.error as Error).message}</p>
          ) : null}
          {!optionsQuery.error && (optionsQuery.isLoading || optionsQuery.isFetching) && options.length === 0 ? (
            <p className="px-2.5 py-1.5 text-body text-ink-faint">{t("handover.userPicker.loading")}</p>
          ) : null}
          {!optionsQuery.error && !optionsQuery.isLoading && options.length === 0 ? (
            <p className="px-2.5 py-1.5 text-body text-ink-faint" data-testid="handover-user-picker-empty">
              {t("handover.userPicker.empty")}
            </p>
          ) : null}
          {!optionsQuery.error
            ? options.map((option, index) => (
                <div
                  key={option.user_id}
                  id={getOptionId(option)}
                  role="option"
                  aria-selected={index === highlightIndex}
                  className={cn(
                    OPTION_BASE_CLASS,
                    index === highlightIndex ? "bg-paper-deep text-ink" : "text-ink-soft hover:bg-paper-deep hover:text-ink",
                  )}
                  onPointerDown={(event) => {
                    event.preventDefault();
                    pick(option);
                  }}
                >
                  <span className="text-body font-medium">{option.name || option.user_id}</span>
                  {option.department ? (
                    <span className="text-xs text-ink-faint">{option.department}</span>
                  ) : null}
                </div>
              ))
            : null}
        </div>
      ) : null}
    </div>
  );
}

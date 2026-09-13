import { useEffect, useId, useState } from "react";

import { TextInput } from "../../components/Field";
import { UserOptionList, useUserCombobox } from "../../components/UserCombobox";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { HandoverCandidate, HandoverUserRef } from "../../lib/domain";
import { handoverCandidatesUrl, type HandoverSurface } from "./surface";

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

  useEffect(() => {
    setInputValue(value?.name ?? "");
  }, [value?.name, value?.user_id]);

  const { open, setOpen, options, optionsQuery, highlightIndex, activeOption, containerRef, onKeyDown, pick } =
    useUserCombobox({
      query: inputValue.trim(),
      optionSource: {
        queryKey: ["handover", "candidates", surface, String(taskId)],
        queryFn: async (debouncedQuery) => {
          const payload = await apiRequest<{ items: HandoverCandidate[] }>(
            handoverCandidatesUrl(surface, taskId, debouncedQuery),
          );
          return payload.items ?? [];
        },
        enabled: !disabled,
        allowEmptyQuery: true,
      },
      debounceMs: 300,
      navigateWhenClosed: false,
      openOnArrowDown: false,
      closeOnPick: true,
      onPick: (option) => {
        onChange({
          user_id: option.user_id,
          name: option.name,
          department: option.department,
        });
        setInputValue(option.name);
      },
    });

  const getOptionId = (option: { user_id: string }) => `${listId}-option-${encodeURIComponent(option.user_id)}`;

  const clear = () => {
    onChange(null);
    setInputValue("");
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
        <UserOptionList
          listId={listId}
          options={options}
          isLoading={optionsQuery.isLoading || optionsQuery.isFetching}
          error={optionsQuery.error as Error | null}
          highlightIndex={highlightIndex}
          getOptionId={getOptionId}
          onPick={pick}
          onRetry={() => void optionsQuery.refetch()}
          emptyLabel={t("handover.userPicker.empty")}
          loadingLabel={t("handover.userPicker.loading")}
          emptyTestId="handover-user-picker-empty"
        />
      ) : null}
    </div>
  );
}

/** 用户选择框共用的键盘导航与候选列表。 */

import { useQuery } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../lib/api";
import type { ListPayload } from "../lib/api";
import { cn } from "../lib/cn";
import type { Translator } from "../lib/status";

export interface UserOption {
  user_id: string;
  name: string;
  /** 部门名; 后端目录未同步到部门时为空串。 */
  department?: string;
  /** 头像地址; 为空表示没有头像, 此时不渲染任何占位图形。 */
  avatar_url?: string;
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

/**
 * 按 user_id 批量解析候选(后端 GET /console/api/v1/user-options?user_ids=a,b&purpose=…)。
 *
 * chip 与回填值里只有 ID, 但界面必须显示姓名: 这里一次查询解析组件内全部未知 ID, 不逐个发请求。
 * purpose 必须跟着调用方走: 审批人候选包含本地紧急管理账号, 用 employee 口径去解析会把它们过滤掉,
 * chip 于是退回裸 ID。后端一次最多接受 50 个 ID, 超了由它报错, 前端不截断也不伪造姓名。
 */
export function useUserOptionsByIds(
  userIds: string[],
  purpose: UserSearchPurpose,
): UseQueryResult<UserOption[], Error> {
  const uniqueSortedIds = [...new Set(userIds)].sort();
  return useQuery({
    queryKey: ["console", "user-options", "by-ids", purpose, uniqueSortedIds],
    queryFn: () =>
      apiRequest<ListPayload<UserOption>>(
        `/console/api/v1/user-options?user_ids=${encodeURIComponent(uniqueSortedIds.join(","))}&purpose=${purpose}`,
      ),
    enabled: uniqueSortedIds.length > 0,
    select: (payload) => itemsFromPayload<UserOption>(payload),
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
  const { t } = useI18n();
  const secondary = userSecondaryLabel(option, t);
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
      <span className="flex items-center gap-2 text-body font-medium">
        {/* 没有头像就不画任何占位图形: 首字母占位会让"未同步头像"和"头像是这个字"看起来一样。 */}
        {option.avatar_url ? (
          <img
            src={option.avatar_url}
            alt=""
            width={20}
            height={20}
            className="h-5 w-5 shrink-0 rounded-full object-cover"
          />
        ) : null}
        <span>{userOptionDisplayName(option)}</span>
      </span>
      {secondary ? <span className="text-xs text-ink-faint">{secondary}</span> : null}
    </div>
  );
}

/** 本地紧急管理账号的 user_id 前缀; 这类账号不在目录里, 没有部门。 */
export const LOCAL_ADMIN_USER_ID_PREFIX = "local-admin:";

/**
 * 人员次行文案: 部门路径, 或本地账号的固定标签。
 *
 * UUID 不能出现在次行 —— 对着一串 Authentik 标识核对「这是谁」不可接受, 部门路径才是认人依据。
 * 本地账号没有部门, 用「本地用户」与目录人员区分; 既不是本地账号又没有部门时返回空串, 调用方不要渲染次行。
 */
export function userSecondaryLabel(
  option: Pick<UserOption, "user_id"> & { department?: string | null },
  t: Translator,
): string {
  if (option.user_id.startsWith(LOCAL_ADMIN_USER_ID_PREFIX)) {
    return t("user.localAccount");
  }
  return option.department?.trim() ?? "";
}

/** 候选行主标题: 只展示姓名(缺失时退回用户 ID)。部门走次行, 避免「姓名 · 部门」与次行重复。 */
export function userOptionDisplayName(option: UserOption): string {
  return userOptionName(option);
}

/**
 * 用户的展示名: 目录里有姓名就用姓名, 否则只能退回用户 ID。
 *
 * 姓名可能是空串(目录镜像没同步到姓名, 见批次契约 A3), 那时显示 ID 是唯一诚实的选择,
 * 不能拿 ID 拼一个假名字。
 */
export function userOptionName(option: UserOption | undefined, fallbackUserId: string = ""): string {
  return option?.name || option?.user_id || fallbackUserId;
}

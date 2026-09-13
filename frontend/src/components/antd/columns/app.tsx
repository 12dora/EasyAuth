import { type ReactNode } from "react";

import { TruncatedText } from "../../TruncatedText";
import type { ColumnType } from "../AppTable";
import { userColumn } from "./person";
import { MONO_TEXT_CLASS } from "./text";

export interface AppColumnConfig<T> {
  key?: string;
  title: ReactNode;
  getDisplayName: (record: T) => string;
  getAppKey: (record: T) => string | null | undefined;
  filter?: boolean;
  width?: number;
}

/**
 * 应用列: 展示名在上、app_key 等宽在下, 截断后悬停才出全文。
 * 两行各自 TruncatedText, 同时只开一个 Tooltip(与 peopleColumn 同口径)。
 * 人员列不要走这里。
 */
export function appColumn<T>({
  filter = false,
  getAppKey,
  getDisplayName,
  key = "app",
  title,
  width = 200,
}: AppColumnConfig<T>): ColumnType<T> {
  const column = userColumn<T>({
    filter,
    getName: getDisplayName,
    getUserId: (record) => getAppKey(record) ?? "",
    key,
    title,
    width,
  });
  return {
    ...column,
    render: (_value, record) => {
      const displayName = getDisplayName(record);
      const appKey = getAppKey(record) ?? "";
      const name = displayName || appKey;
      if (name === "" && appKey === "") {
        return "-";
      }
      // 次行是标识符: 只有主行已有展示名才展示, 避免 app_key 自己复制成两行。
      const showSecondary = Boolean(appKey && displayName);
      return (
        <div className="flex min-w-0 flex-col gap-1">
          <TruncatedText as="strong" text={name} />
          {showSecondary ? <TruncatedText as="code" className={MONO_TEXT_CLASS} text={appKey} /> : null}
        </div>
      );
    },
  };
}

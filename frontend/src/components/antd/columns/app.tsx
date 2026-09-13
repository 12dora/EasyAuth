import { type ReactNode } from "react";

import type { ColumnType } from "../AppTable";
import { userColumn } from "./person";

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
  return userColumn<T>({
    filter,
    getName: getDisplayName,
    getUserId: (record) => getAppKey(record) ?? "",
    key,
    title,
    width,
  });
}

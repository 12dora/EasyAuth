/**
 * 工作区各页签共用的 antd 列预设。
 *
 * 「启用 / 停用」状态列在权限范围、成员、凭据三张表里逐字重复过, 这里收敛成
 * 一处: 页面只说「这行的 is_active 从哪读」, 徽章配色与表头枚举筛选由本文件决定。
 */

import type { ColumnType } from "../../../components/antd/AppTable";
import { statusColumn } from "../../../components/antd/columns";
import type { Translator } from "../../../lib/status";

export function activeStatusColumn<T>({
  t,
  getActive,
  key = "status",
  width = 120,
}: {
  t: Translator;
  getActive: (record: T) => boolean | undefined;
  key?: string;
  width?: number;
}): ColumnType<T> {
  return statusColumn<T>({
    key,
    title: t("common.status"),
    width,
    options: [
      { value: "active", label: t("common.enabled"), tone: "evergreen" },
      { value: "inactive", label: t("common.disabled"), tone: "neutral" },
    ],
    getValue: (record) => (getActive(record) ? "active" : "inactive"),
  });
}

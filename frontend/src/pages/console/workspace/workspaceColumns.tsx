/**
 * 工作区各页签共用的 antd 列预设。
 *
 * 「启用 / 停用」状态列在权限范围、成员、凭据三张表里逐字重复过, 这里收敛成
 * 一处: 页面只说「这行的 is_active 从哪读」, 徽章配色与表头枚举筛选由本文件决定。
 */

import type { ComponentPropsWithoutRef } from "react";

import { Button } from "../../../components/Button";
import type { ColumnType } from "../../../components/antd/AppTable";
import { statusColumn } from "../../../components/antd/columns";
import type { Translator } from "../../../lib/status";

type RowActionVariant = "ghost" | "ghost-danger";

/**
 * 表格行内操作按钮。
 *
 * components/antd 的 actionsColumn 目前仍把按钮外包给 components/ui/TableActions,
 * 但迁移护栏禁止页面继续引入那个模块, 所以这里放一个最小实现: 只是 Button 的
 * size="sm" 预设, 「点击不冒泡到行」已经由 actionsColumn 的容器负责。
 * TODO(地基): 四个页签包都会各自复制一份, 建议上收到 components/antd/columns。
 */
export function RowActionButton({
  variant = "ghost",
  ...props
}: Omit<ComponentPropsWithoutRef<typeof Button>, "size" | "variant"> & { variant?: RowActionVariant }) {
  return <Button size="sm" variant={variant} {...props} />;
}

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

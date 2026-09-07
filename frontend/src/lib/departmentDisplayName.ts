/**
 * 部门展示名的唯一出处。
 *
 * 钉钉的企业根部门在目录镜像里没有名字(`name` 是空串), 但界面上到处都要写它:
 * 组织树的根行、右栏的部门标题与层级、「继承自 X」、弹窗标题与影响范围提示、删除确认。
 * 空名字一律显示成「全公司」, 由调用方传入 `t` 以保证跟随语言切换。
 */

import type { MessageKey } from "../i18n/messages";

export interface DepartmentDisplayNameSource {
  name: string;
}

export function departmentDisplayName(
  source: DepartmentDisplayNameSource,
  t: (key: MessageKey) => string,
): string {
  return source.name.trim() ? source.name : t("departmentGrants.rootDepartment");
}

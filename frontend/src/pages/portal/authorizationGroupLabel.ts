/**
 * 门户里授权组标签的唯一出处。
 *
 * 门户三处(我的授权/我的申请的权限组列、申请表单的权限组下拉、审批详情的事实块)
 * 原本各自把后端枚举 `kind` 原样拼进标签, 员工看到的是 "[role]" 这种接口字面量;
 * 控制台早就翻译过同一枚举, 这里给门户一份共享实现, 文案与控制台保持一致。
 */

import type { AuthorizationGroupKind } from "../../lib/domain";
import type { Translator } from "../../lib/status";

export interface AuthorizationGroupLabelSource {
  key: string;
  kind: AuthorizationGroupKind;
  name: string;
}

export function authorizationGroupKindLabel(kind: AuthorizationGroupKind, t: Translator): string {
  switch (kind) {
    case "role":
      return t("portal.authorizationGroup.kind.role");
    case "bundle":
      return t("portal.authorizationGroup.kind.bundle");
    default:
      // 后端只有 role / bundle 两种; 出现第三种说明契约已经变了, 必须炸出来而不是糊一个 "-"。
      throw new Error(`未知的授权组类别：${String(kind)}`);
  }
}

export function formatAuthorizationGroupLabel(group: AuthorizationGroupLabelSource, t: Translator): string {
  return `${group.name || group.key} [${authorizationGroupKindLabel(group.kind, t)}]`;
}

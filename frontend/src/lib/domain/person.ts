/** 人员展示契约: 与后端 `accounts/person_payload.py` 的 PersonRef 一一对应。 */

export const ACCOUNT_KINDS = ["directory", "local", "unresolved"] as const;

export type AccountKind = (typeof ACCOUNT_KINDS)[number];

export interface PersonRef {
  user_id: string;
  name: string;
  department: string;
  account_kind: AccountKind;
}

/** 账号类型三值校验; 解析人员载荷时走这里, 不得自行推断。 */
export function isAccountKind(value: unknown): value is AccountKind {
  return value === "directory" || value === "local" || value === "unresolved";
}

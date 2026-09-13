/** 人员展示契约: 与后端 `accounts/person_payload.py` 的 PersonRef 一一对应。 */

export type AccountKind = "directory" | "local";

export interface PersonRef {
  user_id: string;
  name: string;
  department: string;
  account_kind: AccountKind;
}

/** 人员展示契约: 与后端 `accounts/person_payload.py` 的 PersonRef 一一对应。 */

export const ACCOUNT_KINDS = ["directory", "local", "unresolved"] as const;

export type AccountKind = (typeof ACCOUNT_KINDS)[number];

export interface PersonRef {
  user_id: string;
  name: string;
  department: string;
  account_kind: AccountKind;
  /**
   * 头像 URL。无照片时为空串。
   * Authentik 在没有钉钉照片时会下发 `data:image/svg+xml;base64,...` 首字母图; EasyAuth 按照片渲染。
   * 渲染层再走 `safeAvatarUrl`, 只接受 https、同源相对路径与白名单内联 base64 图。
   */
  avatar_url: string;
}

export class PersonContractError extends Error {
  constructor(readonly field: string) {
    super(`人员契约违约: ${field}`);
    this.name = "PersonContractError";
  }
}

/** 账号类型三值校验; 解析人员载荷时走这里, 不得自行推断。 */
export function isAccountKind(value: unknown): value is AccountKind {
  return value === "directory" || value === "local" || value === "unresolved";
}

/**
 * 从未知 JSON 读取 PersonRef。五字段必填, `account_kind` 必须是三值之一;
 * `avatar_url` 必须是字符串(无照片时为空串)。缺字段或非法值立即失败。
 */
export function readPersonRef(raw: unknown, field = "person"): PersonRef {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new PersonContractError(field);
  }
  const source = raw as Record<string, unknown>;
  if (typeof source.user_id !== "string") {
    throw new PersonContractError(`${field}.user_id`);
  }
  if (typeof source.name !== "string") {
    throw new PersonContractError(`${field}.name`);
  }
  if (typeof source.department !== "string") {
    throw new PersonContractError(`${field}.department`);
  }
  if (!isAccountKind(source.account_kind)) {
    throw new PersonContractError(`${field}.account_kind`);
  }
  if (typeof source.avatar_url !== "string") {
    throw new PersonContractError(`${field}.avatar_url`);
  }
  return {
    user_id: source.user_id,
    name: source.name,
    department: source.department,
    account_kind: source.account_kind,
    avatar_url: source.avatar_url,
  };
}

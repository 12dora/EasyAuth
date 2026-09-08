/**
 * 授权成员关系(权限组 / 展开权限)的共享展示口径, 门户与控制台共用。
 */

/** 权限组列只需要 key 与 name; 门户与控制台的行类型都带着更多字段, 这里只取用到的两个。 */
export interface GrantGroupName {
  key: string;
  name: string;
}

/**
 * 权限组列文案: 只显示组名。
 *
 * 后面再挂一个 `[角色]` / `[权限包]` 是给管理员分辨授权模型用的, 与「有哪些权限组」
 * 这个问题无关。目录行被删掉时后端下发的 name 会是空串, 这时退回展示 key,
 * 至少还能定位到是哪一个组。
 */
export function formatGrantGroupNames(groups: readonly GrantGroupName[]): string {
  if (groups.length === 0) {
    return "-";
  }
  return groups.map((group) => group.name || group.key).join("、");
}

/**
 * 门户面向员工的两张表(「我的权限」「我的申请」)的权限组列文案。
 *
 * 只显示组名: 后面再挂一个 `[角色]` / `[权限包]` 是给管理员分辨授权模型用的,
 * 与员工「我有哪些权限组」的问题无关。目录行被删掉时后端下发的 name 会是空串,
 * 这时退回展示 key, 至少还能定位到是哪一个组。
 */
export function formatGrantGroupNames(groups: readonly { key: string; name: string }[]): string {
  if (groups.length === 0) {
    return "-";
  }
  return groups.map((group) => group.name || group.key).join("、");
}

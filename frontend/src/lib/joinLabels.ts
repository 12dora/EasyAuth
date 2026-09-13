/**
 * 多值文案拼接: 丢掉空串, 用统一分隔符连接, 全空时给出占位。
 * 人员/权限组/负责人列表不要各自发明 "—" 或 ", "。
 */
export function joinLabels(
  values: readonly (string | null | undefined)[] | undefined,
  {
    empty = "-",
    separator = "、",
  }: {
    empty?: string;
    separator?: string;
  } = {},
): string {
  const parts = (values ?? []).filter((value): value is string => typeof value === "string" && value !== "");
  return parts.length > 0 ? parts.join(separator) : empty;
}

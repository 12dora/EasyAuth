export function getTableColumnCount(columnCount: number | null | undefined): number {
  return Math.max(1, columnCount ?? 1);
}

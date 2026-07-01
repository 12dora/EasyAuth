export function getTableColumnCount(columnCount: number | null | undefined): number {
  return Math.max(1, columnCount ?? 1);
}

export function hasTableRows<T>(rows: readonly T[] | null | undefined): boolean {
  return Boolean(rows?.length);
}

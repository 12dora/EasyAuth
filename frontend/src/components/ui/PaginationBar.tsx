import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "../Button";
import { SelectInput } from "../Field";

export const DEFAULT_TABLE_PAGE_SIZE = 10;
export const TABLE_PAGE_SIZE_OPTIONS = [5, 10, 20, 50] as const;

interface PaginationBarProps {
  pageStart: number;
  pageEnd: number;
  totalRows: number;
  pageSize: number;
  pageIndex: number;
  pageCount: number;
  canPreviousPage: boolean;
  canNextPage: boolean;
  onPageSizeChange: (pageSize: number) => void;
  onPreviousPage: () => void;
  onNextPage: () => void;
}

export function PaginationBar({
  pageStart,
  pageEnd,
  totalRows,
  pageSize,
  pageIndex,
  pageCount,
  canPreviousPage,
  canNextPage,
  onPageSizeChange,
  onPreviousPage,
  onNextPage,
}: PaginationBarProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 bg-paper-deep/30 px-3 py-2.5">
      <span className="text-caption font-medium text-ink-soft">
        第 {pageStart}-{pageEnd} 条 / 共 {totalRows} 条
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-caption font-medium text-ink-soft">
          每页
          <SelectInput
            aria-label="每页条目数"
            className="h-8 w-20"
            value={String(pageSize)}
            onChange={(event) => onPageSizeChange(Number(event.currentTarget.value))}
          >
            {TABLE_PAGE_SIZE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </SelectInput>
        </label>
        <div className="flex items-center gap-1">
          <Button
            aria-label="上一页"
            icon={<ChevronLeft size={15} />}
            disabled={!canPreviousPage}
            onClick={onPreviousPage}
            size="sm"
            type="button"
          />
          <span className="min-w-16 text-center font-mono text-caption text-ink-soft">
            {pageCount === 0 ? 0 : pageIndex + 1} / {pageCount}
          </span>
          <Button
            aria-label="下一页"
            icon={<ChevronRight size={15} />}
            disabled={!canNextPage}
            onClick={onNextPage}
            size="sm"
            type="button"
          />
        </div>
      </div>
    </div>
  );
}

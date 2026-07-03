import type { ComponentPropsWithoutRef } from "react";

import { cn } from "../../lib/cn";
import { getTableColumnCount } from "./TableState";
import {
  TABLE_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_HEADER_CELL_CLASS,
  TABLE_ROOT_CLASS,
  TABLE_ROW_CLASS,
} from "./tableStyles";

type DivProps = ComponentPropsWithoutRef<"div">;
type TableProps = ComponentPropsWithoutRef<"table">;
type SectionProps = ComponentPropsWithoutRef<"thead">;
type BodyProps = ComponentPropsWithoutRef<"tbody">;
type RowProps = ComponentPropsWithoutRef<"tr">;
type HeaderCellProps = ComponentPropsWithoutRef<"th">;
type CellProps = ComponentPropsWithoutRef<"td">;

export function TableFrame({ className, children, ...props }: DivProps) {
  return (
    <div className={cn("paper-card overflow-hidden rounded-[3px] p-0", className)} {...props}>
      <div className="overflow-x-auto">{children}</div>
    </div>
  );
}

export function TableRoot({ className, children, ...props }: TableProps) {
  return (
    <table className={cn(TABLE_ROOT_CLASS, className)} {...props}>
      {children}
    </table>
  );
}

export function TableHead({ className, children, ...props }: SectionProps) {
  return (
    <thead className={cn(TABLE_HEAD_CLASS, className)} {...props}>
      {children}
    </thead>
  );
}

export function TableBody({ className, children, ...props }: BodyProps) {
  return <tbody className={className} {...props}>{children}</tbody>;
}

export function TableRow({ className, children, ...props }: RowProps) {
  return (
    <tr className={cn(TABLE_ROW_CLASS, className)} {...props}>
      {children}
    </tr>
  );
}

export function TableHeaderCell({ className, children, ...props }: HeaderCellProps) {
  return (
    <th className={cn(TABLE_HEADER_CELL_CLASS, className)} {...props}>
      {children}
    </th>
  );
}

export function TableCell({ className, children, ...props }: CellProps) {
  return (
    <td className={cn(TABLE_CELL_CLASS, className)} {...props}>
      {children}
    </td>
  );
}

export function TableEmptyRow({
  colSpan,
  children,
  className,
}: {
  colSpan: number;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={getTableColumnCount(colSpan)} className={cn("py-10 text-center text-ink-soft", className)}>
        {children}
      </TableCell>
    </TableRow>
  );
}

export function TableSkeletonRows({
  columns,
  rows = 3,
}: {
  columns: number;
  rows?: number;
}) {
  const columnCount = getTableColumnCount(columns);
  return (
    <>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TableRow key={rowIndex} aria-hidden="true">
          {Array.from({ length: columnCount }).map((__, columnIndex) => (
            <TableCell key={columnIndex}>
              <span className="block h-3 w-full max-w-32 animate-shimmer rounded-[2px] bg-paper-deep" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

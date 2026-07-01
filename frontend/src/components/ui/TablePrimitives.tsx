import type { ComponentPropsWithoutRef } from "react";

import { getTableColumnCount } from "./TableState";

type DivProps = ComponentPropsWithoutRef<"div">;
type TableProps = ComponentPropsWithoutRef<"table">;
type SectionProps = ComponentPropsWithoutRef<"thead">;
type BodyProps = ComponentPropsWithoutRef<"tbody">;
type RowProps = ComponentPropsWithoutRef<"tr">;
type HeaderCellProps = ComponentPropsWithoutRef<"th">;
type CellProps = ComponentPropsWithoutRef<"td">;

export function TableFrame({ className, children, ...props }: DivProps) {
  return (
    <div
      className={joinClassNames(
        "overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-sm shadow-slate-200/50",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function TableRoot({ className, children, ...props }: TableProps) {
  return (
    <table className={joinClassNames("w-full min-w-max border-separate border-spacing-0 text-left text-sm", className)} {...props}>
      {children}
    </table>
  );
}

export function TableHead({ className, children, ...props }: SectionProps) {
  return (
    <thead className={joinClassNames("bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500", className)} {...props}>
      {children}
    </thead>
  );
}

export function TableBody({ className, children, ...props }: BodyProps) {
  return (
    <tbody className={joinClassNames("divide-y divide-slate-100 bg-white text-slate-700", className)} {...props}>
      {children}
    </tbody>
  );
}

export function TableRow({ className, children, ...props }: RowProps) {
  return (
    <tr className={joinClassNames("transition-colors hover:bg-slate-50/80", className)} {...props}>
      {children}
    </tr>
  );
}

export function TableHeaderCell({ className, children, ...props }: HeaderCellProps) {
  return (
    <th className={joinClassNames("whitespace-nowrap px-4 py-3 align-middle first:pl-5 last:pr-5", className)} {...props}>
      {children}
    </th>
  );
}

export function TableCell({ className, children, ...props }: CellProps) {
  return (
    <td className={joinClassNames("px-4 py-3 align-middle first:pl-5 last:pr-5", className)} {...props}>
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
      <TableCell colSpan={getTableColumnCount(colSpan)} className={joinClassNames("py-10 text-center text-slate-500", className)}>
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
              <span className="block h-3 w-full max-w-32 animate-pulse rounded bg-slate-100" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

function joinClassNames(...classNames: Array<string | false | null | undefined>): string {
  return classNames.filter(Boolean).join(" ");
}

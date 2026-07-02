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
    <div className={joinClassNames("paper-card overflow-hidden rounded-[3px] p-0", className)} {...props}>
      <div className="overflow-x-auto">{children}</div>
    </div>
  );
}

export function TableRoot({ className, children, ...props }: TableProps) {
  return (
    <table className={joinClassNames("min-w-full border-separate border-spacing-0 text-[13px]", className)} {...props}>
      {children}
    </table>
  );
}

export function TableHead({ className, children, ...props }: SectionProps) {
  return (
    <thead className={joinClassNames("bg-paper-deep/60", className)} {...props}>
      {children}
    </thead>
  );
}

export function TableBody({ className, children, ...props }: BodyProps) {
  return <tbody className={className} {...props}>{children}</tbody>;
}

export function TableRow({ className, children, ...props }: RowProps) {
  return (
    <tr className={joinClassNames("group transition-colors hover:bg-[rgb(var(--amber))]/[0.05]", className)} {...props}>
      {children}
    </tr>
  );
}

export function TableHeaderCell({ className, children, ...props }: HeaderCellProps) {
  return (
    <th
      className={joinClassNames(
        "border-b border-ink/15 px-3 py-2.5 text-left align-bottom font-mono text-[10.5px] uppercase tracking-[0.14em] text-ink-soft font-medium",
        className,
      )}
      {...props}
    >
      {children}
    </th>
  );
}

export function TableCell({ className, children, ...props }: CellProps) {
  return (
    <td className={joinClassNames("border-b border-ink/8 px-3 py-2.5 text-[13px] text-ink align-middle", className)} {...props}>
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
      <TableCell colSpan={getTableColumnCount(colSpan)} className={joinClassNames("py-10 text-center text-ink-soft", className)}>
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

function joinClassNames(...classNames: Array<string | false | null | undefined>): string {
  return classNames.filter(Boolean).join(" ");
}

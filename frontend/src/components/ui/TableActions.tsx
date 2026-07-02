import type { ComponentPropsWithoutRef, MouseEvent, ReactNode } from "react";

import { Button } from "../Button";
import { TableCell } from "./TablePrimitives";

type TableActionVariant = "ghost" | "ghost-danger";
type TableActionButtonProps = Omit<ComponentPropsWithoutRef<typeof Button>, "size" | "variant"> & {
  variant?: TableActionVariant;
};
type TableActionLinkProps = Omit<ComponentPropsWithoutRef<"a">, "className"> & {
  className?: string;
  icon?: ReactNode;
  variant?: TableActionVariant;
};

const LINK_VARIANT_CLASSES: Record<TableActionVariant, string> = {
  ghost: "border-transparent bg-transparent text-ink-soft hover:bg-ink/[0.04] hover:text-ink active:[transform:translateY(1px)]",
  "ghost-danger": "border-transparent bg-transparent text-signal hover:bg-signal/10 active:[transform:translateY(1px)]",
};

export function TableActionCell({ className, children, ...props }: ComponentPropsWithoutRef<"td">) {
  return (
    <TableCell className={joinClassNames("w-0 whitespace-nowrap text-right", className)} {...props}>
      <div className="flex items-center justify-end gap-1.5" onClick={stopRowClick} onDoubleClick={stopRowClick}>
        {children}
      </div>
    </TableCell>
  );
}

export function TableRowActionButton({ variant = "ghost", onClick, ...props }: TableActionButtonProps) {
  return (
    <Button
      size="sm"
      variant={variant}
      onClick={(event) => {
        event.stopPropagation();
        onClick?.(event);
      }}
      {...props}
    />
  );
}

export function TableRowActionLink({
  className,
  children,
  icon,
  variant = "ghost",
  onClick,
  ...props
}: TableActionLinkProps) {
  return (
    <a
      className={joinClassNames(
        "inline-flex h-7 shrink-0 items-center justify-center gap-2 rounded-[2px] border px-2.5 text-[12px] font-medium tracking-wide transition-all duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--amber)_/_0.5)]",
        LINK_VARIANT_CLASSES[variant],
        className,
      )}
      onClick={(event) => {
        event.stopPropagation();
        onClick?.(event);
      }}
      {...props}
    >
      {icon ? (
        <span className="inline-flex size-4 items-center justify-center" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children ? <span>{children}</span> : null}
    </a>
  );
}

function stopRowClick(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
}

function joinClassNames(...classNames: Array<string | false | null | undefined>): string {
  return classNames.filter(Boolean).join(" ");
}

import type { ComponentPropsWithoutRef, MouseEvent, ReactNode } from "react";

import { cn } from "../../lib/cn";
import { Button, BUTTON_BASE_CLASSES, BUTTON_SIZE_CLASSES, BUTTON_VARIANT_CLASSES } from "../Button";
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

export function TableActionCell({ className, children, ...props }: ComponentPropsWithoutRef<"td">) {
  return (
    <TableCell className={cn("w-0 whitespace-nowrap text-right", className)} {...props}>
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
      className={cn(BUTTON_BASE_CLASSES, BUTTON_VARIANT_CLASSES[variant], BUTTON_SIZE_CLASSES.sm, className)}
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

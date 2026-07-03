import type { AnchorHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";

import { cn } from "../lib/cn";
import { BUTTON_BASE_CLASSES, BUTTON_SIZE_CLASSES, BUTTON_VARIANT_CLASSES } from "./Button";
import type { ButtonSize, ButtonVariant } from "./Button";

interface ButtonLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  to?: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
}

export function ButtonLink({
  className,
  to,
  href,
  icon,
  size = "md",
  variant = "outline",
  children,
  ...props
}: ButtonLinkProps) {
  const classes = cn(BUTTON_BASE_CLASSES, BUTTON_VARIANT_CLASSES[variant], BUTTON_SIZE_CLASSES[size], className);
  const content = (
    <>
      {icon ? (
        <span className="inline-flex size-4 items-center justify-center" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children ? <span>{children}</span> : null}
    </>
  );

  if (to) {
    return (
      <Link className={classes} to={to} {...props}>
        {content}
      </Link>
    );
  }
  return (
    <a className={classes} href={href} {...props}>
      {content}
    </a>
  );
}

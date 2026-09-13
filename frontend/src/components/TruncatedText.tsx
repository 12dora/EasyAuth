/** 超长文本截断; 仅在确实溢出时用 Tooltip 展示全文。 */

import { Tooltip } from "antd";
import { useCallback, useState, type FocusEvent, type MouseEvent } from "react";

import { cn } from "../lib/cn";

export function TruncatedText({
  text,
  className,
  as: Tag = "span",
}: {
  text: string;
  className?: string;
  as?: "span" | "code";
}) {
  const [open, setOpen] = useState(false);

  const measureAndOpen = useCallback((element: HTMLElement) => {
    setOpen(element.scrollWidth > element.clientWidth);
  }, []);

  const onMouseEnter = (event: MouseEvent<HTMLElement>) => {
    measureAndOpen(event.currentTarget);
  };
  const onFocus = (event: FocusEvent<HTMLElement>) => {
    measureAndOpen(event.currentTarget);
  };
  const close = () => setOpen(false);

  return (
    <Tooltip title={text} open={open}>
      <Tag
        className={cn("truncate", className)}
        onMouseEnter={onMouseEnter}
        onMouseLeave={close}
        onFocus={onFocus}
        onBlur={close}
      >
        {text}
      </Tag>
    </Tooltip>
  );
}

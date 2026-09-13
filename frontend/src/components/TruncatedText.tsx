/** 超长文本截断; 仅在确实溢出时用 Tooltip 展示全文。 */

import { Tooltip } from "antd";
import { useCallback, useLayoutEffect, useState, type FocusEvent, type MouseEvent, type ReactNode } from "react";

import { cn } from "../lib/cn";

export function TruncatedText({
  text,
  className,
  as: Tag = "span",
  children,
}: {
  text: string;
  className?: string;
  as?: "span" | "code";
  /** 可见内容; 缺省渲染 `text`。溢出时 Tooltip 仍展示 `text`(例如一行姓名的拼接全文)。 */
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    setOpen(false);
  }, [text]);

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
        {children ?? text}
      </Tag>
    </Tooltip>
  );
}

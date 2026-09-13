/** 超长文本截断; 仅在确实溢出时用 Tooltip 展示全文。 */

import { Tooltip } from "antd";
import { useCallback, useLayoutEffect, useState, type FocusEvent, type MouseEvent, type ReactNode } from "react";

import { cn } from "../lib/cn";

const TOOLTIP_CHILD_SELECTOR = "[data-tooltip-child]";

export type TruncatedTextHoverEvent = MouseEvent<HTMLElement> | FocusEvent<HTMLElement>;

function eventTargetElement(target: EventTarget | null): Element | null {
  if (target instanceof Element) {
    return target;
  }
  if (target instanceof Node) {
    return target.parentElement;
  }
  return null;
}

/**
 * 指针/焦点是否落在标了 `data-tooltip-child` 的子孙上。
 * 这类子节点自己有 Tooltip(例如 PeopleLine 的姓名), 溢出 Tooltip 不得再开。
 */
export function isTooltipChildTarget(event: { target: EventTarget | null; currentTarget: EventTarget }): boolean {
  const target = eventTargetElement(event.target);
  if (target === null) {
    return false;
  }
  const child = target.closest(TOOLTIP_CHILD_SELECTOR);
  return child !== null && event.currentTarget instanceof Node && event.currentTarget.contains(child);
}

export function TruncatedText({
  text,
  title,
  className,
  as: Tag = "span",
  children,
  isChildTarget,
}: {
  text: string;
  className?: string;
  as?: "span" | "code";
  /** 可见内容; 缺省渲染 `text`。溢出 Tooltip 展示 `title ?? text`。 */
  children?: ReactNode;
  /** 溢出时 Tooltip 内容; 缺省为 `text`。 */
  title?: ReactNode;
  /**
   * 为真则不打开溢出 Tooltip。未传时认 `data-tooltip-child`。
   * mouseover 也会走同一判断, 以便从空白处移入子节点时关掉已打开的溢出 Tooltip。
   */
  isChildTarget?: (event: TruncatedTextHoverEvent) => boolean;
}) {
  const [open, setOpen] = useState(false);

  useLayoutEffect(() => {
    setOpen(false);
  }, [text]);

  const measureAndOpen = useCallback((element: HTMLElement) => {
    setOpen(element.scrollWidth > element.clientWidth);
  }, []);

  const fromChild = (event: TruncatedTextHoverEvent) =>
    isChildTarget ? isChildTarget(event) : isTooltipChildTarget(event);

  const onHover = (event: MouseEvent<HTMLElement>) => {
    if (fromChild(event)) {
      setOpen(false);
      return;
    }
    measureAndOpen(event.currentTarget);
  };
  const onFocus = (event: FocusEvent<HTMLElement>) => {
    if (fromChild(event)) {
      setOpen(false);
      return;
    }
    measureAndOpen(event.currentTarget);
  };
  const close = () => setOpen(false);

  return (
    <Tooltip title={title ?? text} open={open}>
      <Tag
        className={cn("truncate", className)}
        onMouseEnter={onHover}
        onMouseOver={onHover}
        onMouseLeave={close}
        onFocus={onFocus}
        onBlur={close}
      >
        {children ?? text}
      </Tag>
    </Tooltip>
  );
}

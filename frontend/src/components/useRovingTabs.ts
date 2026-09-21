import { useLayoutEffect, useState, type KeyboardEvent, type RefObject } from "react";

interface RovingTabsOptions<T extends string> {
  activeKey: T;
  items: readonly T[];
  refs: RefObject<Array<HTMLButtonElement | null>>;
  onActivate: (key: T) => void;
}

export function useRovingTabs<T extends string>({ activeKey, items, refs, onActivate }: RovingTabsOptions<T>) {
  return (event: KeyboardEvent<HTMLDivElement>) => {
    const activeIndex = Math.max(0, items.indexOf(activeKey));
    const nextIndex =
      event.key === "ArrowRight"
        ? (activeIndex + 1) % items.length
        : event.key === "ArrowLeft"
          ? (activeIndex - 1 + items.length) % items.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? items.length - 1
              : -1;

    if (nextIndex === -1) {
      return;
    }

    event.preventDefault();
    const nextKey = items[nextIndex];
    onActivate(nextKey);
    window.requestAnimationFrame(() => refs.current[nextIndex]?.focus());
  };
}

export interface TabIndicatorStyle {
  left: number;
  width: number;
}

/**
 * 让下划线指示器跟随当前页签按钮的位置与宽度(含容器/窗口尺寸变化)。
 *
 * 位移与宽度是像素值, 只能在布局后量;
 * 过渡时长与缓动由调用方的 class 决定, 这里只负责几何。
 */
export function useActiveTabIndicator(
  tabButtonRefs: RefObject<Array<HTMLButtonElement | null>>,
  activeTabIndex: number,
): TabIndicatorStyle {
  const [indicatorStyle, setIndicatorStyle] = useState<TabIndicatorStyle>({ left: 0, width: 0 });

  useLayoutEffect(() => {
    const activeButton = tabButtonRefs.current[activeTabIndex];
    if (!activeButton) {
      return;
    }
    const updateIndicator = () => {
      setIndicatorStyle({
        left: activeButton.offsetLeft,
        width: activeButton.offsetWidth,
      });
    };

    updateIndicator();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateIndicator);
    observer?.observe(activeButton);
    if (activeButton.parentElement) {
      observer?.observe(activeButton.parentElement);
    }
    window.addEventListener("resize", updateIndicator);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateIndicator);
    };
  }, [activeTabIndex, tabButtonRefs]);

  return indicatorStyle;
}

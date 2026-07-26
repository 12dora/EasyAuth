import type { KeyboardEvent, RefObject } from "react";

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

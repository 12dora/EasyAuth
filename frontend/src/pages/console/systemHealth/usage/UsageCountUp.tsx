import { useEffect, useRef, useState } from "react";

import { useI18n } from "../../../../i18n/I18nProvider";
import { prefersReducedMotion } from "./usageChartModel";
import { formatUsageCount } from "./usageMeterModel";

const COUNT_UP_MS = 650;

/**
 * 计量卡的大数字: 数值变化时从当前显示值滚到新值。
 *
 * 首帧不做动画(从 0 滚上来会让首屏读数抖一下), 只有刷新拿到新数才滚。
 */
export function UsageCountUp({ value, className }: { value: number; className?: string }) {
  const { locale } = useI18n();
  const [display, setDisplay] = useState(value);
  const paintedRef = useRef(value);

  useEffect(() => {
    const from = paintedRef.current;
    if (from === value) {
      return;
    }
    if (prefersReducedMotion() || typeof requestAnimationFrame !== "function") {
      paintedRef.current = value;
      setDisplay(value);
      return;
    }
    let frame = 0;
    const startedAt = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / COUNT_UP_MS);
      // ease-out cubic: 与 --ease-out-paper 同一种「快进慢出」的手感。
      const eased = 1 - (1 - progress) ** 3;
      const next = Math.round(from + (value - from) * eased);
      paintedRef.current = next;
      setDisplay(next);
      if (progress < 1) {
        frame = requestAnimationFrame(step);
      }
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return (
    <span className={className} data-testid="usage-count-up">
      {formatUsageCount(display, locale)}
    </span>
  );
}

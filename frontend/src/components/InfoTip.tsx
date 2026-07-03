import { Info } from "lucide-react";

interface InfoTipProps {
  text: string;
  label?: string;
}

/** i 图标提示: hover 或聚焦时展示说明文字。 */
export function InfoTip({ text, label }: InfoTipProps) {
  return (
    <span className="group relative inline-flex items-center">
      <button
        type="button"
        aria-label={label ?? text}
        className="inline-flex cursor-help items-center text-ink-faint transition-colors hover:text-ink-soft focus-visible:text-ink-soft"
      >
        <Info size={13} aria-hidden="true" />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute left-1/2 top-full z-30 mt-1.5 w-64 -translate-x-1/2 rounded-[3px] bg-ink px-2.5 py-1.5 text-xs font-normal normal-case leading-5 tracking-normal text-paper opacity-0 shadow-lg transition-opacity duration-150 group-focus-within:opacity-100 group-hover:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

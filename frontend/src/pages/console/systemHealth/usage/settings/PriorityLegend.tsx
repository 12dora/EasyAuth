import { Badge } from "../../../../../components/Badge";
import { useI18n } from "../../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../../i18n/messages";
import type { BadgeTone } from "../../../../../lib/status";

const ROWS: ReadonlyArray<{ tone: BadgeTone; labelKey: MessageKey; textKey: MessageKey }> = [
  { tone: "bond", labelKey: "usageSettings.priority.p0", textKey: "usageSettings.legend.p0" },
  { tone: "neutral", labelKey: "usageSettings.priority.p1", textKey: "usageSettings.legend.p1" },
  { tone: "faint", labelKey: "usageSettings.priority.p2", textKey: "usageSettings.legend.p2" },
];

/** P0/P1/P2 的解释: 折叠在策略下方, 需要时才展开, 用原生 details 保证键盘可用。 */
export function PriorityLegend() {
  const { t } = useI18n();

  return (
    <details className="rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2">
      <summary className="cursor-pointer text-caption font-medium text-ink-soft marker:text-ink-faint hover:text-ink">
        {t("usageSettings.legend.toggle")}
      </summary>
      <ul className="mt-2 space-y-1.5">
        {ROWS.map((row) => (
          <li key={row.labelKey} className="flex items-start gap-2 text-caption leading-5 text-ink-soft">
            <Badge tone={row.tone}>{t(row.labelKey)}</Badge>
            <span className="min-w-0">{t(row.textKey)}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

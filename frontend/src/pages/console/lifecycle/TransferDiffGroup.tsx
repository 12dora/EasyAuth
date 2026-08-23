import { useI18n } from "../../../i18n/I18nProvider";
import type { TransferGrantDiffEntry } from "../../../lib/domain";
import { grantNameMapKey } from "./handoverTaskDetailModel";
import { parseGrantDiffKey } from "./lifecycleLabels";

export interface TransferDiffGroupProps {
  title: string;
  entries: TransferGrantDiffEntry[];
  nameMap: Map<string, string>;
  readOnly: boolean;
  checked: Record<string, boolean> | null;
  onToggle?: (key: string, value: boolean) => void;
}

export function TransferDiffGroup({ title, entries, nameMap, readOnly, checked, onToggle }: TransferDiffGroupProps) {
  const { t } = useI18n();
  return (
    <div className="space-y-2 rounded-[3px] border border-ink/10 bg-paper-soft p-3">
      <h3 className="text-body font-semibold text-ink">
        {title}
        <span className="ml-1.5 text-caption font-normal text-ink-faint">{entries.length}</span>
      </h3>
      {entries.length === 0 ? (
        <p className="text-caption text-ink-faint">{t("handover.transfer.emptyGroup")}</p>
      ) : (
        <ul className="grid gap-1.5">
          {entries.map((entry) => (
            <li key={entry.key}>
              {checked === null ? (
                <DiffEntryLabel entry={entry} nameMap={nameMap} />
              ) : (
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-1"
                    disabled={readOnly}
                    checked={checked[entry.key] ?? true}
                    onChange={(event) => onToggle?.(entry.key, event.currentTarget.checked)}
                  />
                  <DiffEntryLabel entry={entry} nameMap={nameMap} />
                </label>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function DiffEntryLabel({ entry, nameMap }: { entry: TransferGrantDiffEntry; nameMap: Map<string, string> }) {
  const { t } = useI18n();
  const parsed = parseGrantDiffKey(entry.key);
  const mappedName = entry.name || nameMap.get(grantNameMapKey(parsed));
  const kindLabel = parsed.kind === "group" ? t("handover.diff.kind.group") : t("handover.diff.kind.permission");
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="text-body text-ink">{mappedName || parsed.key || entry.key}</span>
      <span className="text-caption text-ink-faint">
        {parsed.appKey}
        {" · "}
        {kindLabel}
        {parsed.scopeKey ? ` · ${parsed.scopeKey}` : ""}
      </span>
    </span>
  );
}

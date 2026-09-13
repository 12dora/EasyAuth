import { Tooltip } from "antd";
import type { MouseEvent, ReactNode } from "react";

export function requireGrantLockedHint(
  lockedGroupKeys: string[],
  lockedSelectionKeys: string[],
  lockedHint: string | undefined,
): string {
  if (lockedGroupKeys.length === 0 && lockedSelectionKeys.length === 0) {
    return "";
  }
  if (!lockedHint) {
    throw new Error("GrantForm: lockedHint is required when locked keys are present");
  }
  return lockedHint;
}

export function wrapLockedSelectContent(
  value: string,
  label: ReactNode,
  lockedGroupKeySet: Set<string>,
  lockedHint: string,
): ReactNode {
  if (!lockedGroupKeySet.has(value) || !lockedHint) {
    return label;
  }
  return (
    <Tooltip title={lockedHint}>
      <span className="inline-flex w-full cursor-not-allowed pointer-events-auto">
        {label}
      </span>
    </Tooltip>
  );
}

export function LockedSelectTag({
  label,
  value,
  closable,
  onClose,
  lockedGroupKeySet,
  lockedHint,
}: {
  label: ReactNode;
  value: string;
  closable: boolean;
  onClose: (event: MouseEvent<HTMLElement>) => void;
  lockedGroupKeySet: Set<string>;
  lockedHint: string;
}) {
  const locked = lockedGroupKeySet.has(value);
  const onPreventMouseDown = (event: MouseEvent<HTMLSpanElement>) => {
    event.preventDefault();
    event.stopPropagation();
  };
  const tag = (
    <span
      className="ant-select-selection-item"
      onMouseDown={onPreventMouseDown}
    >
      <span className="ant-select-selection-item-content">{label}</span>
      {closable && !locked ? (
        <span
          className="ant-select-selection-item-remove"
          onClick={onClose}
          role="img"
          aria-label="close"
        >
          ×
        </span>
      ) : null}
    </span>
  );
  if (!locked || !lockedHint) {
    return tag;
  }
  return (
    <Tooltip title={lockedHint}>
      <span className="inline-flex cursor-not-allowed">{tag}</span>
    </Tooltip>
  );
}

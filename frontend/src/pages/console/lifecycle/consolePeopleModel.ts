import type { PersonRow } from "../../../lib/domain";

export const PEOPLE_QUERY_PREFIX = ["console", "people"];
export const DEFAULT_PAGE_SIZE = 20;
export const PERSON_STATUSES = ["active", "disabled", "departed"] as const;

export type HandoverKind = "offboard" | "transfer";

export interface HandoverStartTarget {
  person: PersonRow;
  kind: HandoverKind;
}

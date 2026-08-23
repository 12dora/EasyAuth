import type { ExpandedGrantItem, QueryTestResult } from "../../../../lib/domain";

export type QueryTestGroup = { key?: string; name?: string; source?: string; snapshot_version?: string };

export type QueryTestGrant = Partial<ExpandedGrantItem> & {
  permission?: string;
  scope?: string;
  source_type?: string;
  source_key?: string;
  name?: string;
  snapshot_version?: string;
  grant_type?: string;
};

export type StructuredQueryTestResult = QueryTestResult & {
  source?: string;
  snapshot_version?: string;
  groups?: QueryTestGroup[];
  grants?: QueryTestGrant[];
};

/**
 * 「来自组织授权」提示框: 直接授权页与员工申请表共用。
 *
 * 进出场走同一套高度 + 透明度 + 轻微位移过渡; 退出期间上一份内容保持挂载,
 * 换应用时现状查询短暂没有 data 也不会把下面的表单顶得跳一下。
 * 换被授权人必须立刻卸掉, 不能把上一个人的组织授权留在这一格。
 */

import { useEffect, useState } from "react";

import { cn } from "../../lib/cn";

export type DepartmentSourcedNoticeStatus = "idle" | "pending" | "success" | "error";

export interface DepartmentSourcedGrantLike {
  authorization_groups: readonly {
    key: string;
    name: string;
    source: string;
  }[];
  direct_grants: readonly {
    permission: string;
    permission_name: string;
    scope: string;
    scope_name: string;
    source: string;
  }[];
}

export interface DepartmentSourcedContent {
  groups: { key: string; name: string }[];
  permissions: { permission: string; permission_name: string; scope: string; scope_name: string }[];
}

export function departmentSourcedNoticeStatus(
  ready: boolean,
  query: { isSuccess: boolean; isError: boolean },
): DepartmentSourcedNoticeStatus {
  if (!ready) {
    return "idle";
  }
  if (query.isError) {
    return "error";
  }
  if (query.isSuccess) {
    return "success";
  }
  return "pending";
}

export function departmentSourcedContent(grant: DepartmentSourcedGrantLike | null): DepartmentSourcedContent {
  return {
    groups: (grant?.authorization_groups ?? [])
      .filter((group) => group.source === "department")
      .map((group) => ({ key: group.key, name: group.name })),
    permissions: (grant?.direct_grants ?? [])
      .filter((permission) => permission.source === "department")
      .map((permission) => ({
        permission: permission.permission,
        permission_name: permission.permission_name,
        scope: permission.scope,
        scope_name: permission.scope_name,
      })),
  };
}

export function departmentSourcedContentHasItems(content: DepartmentSourcedContent): boolean {
  return content.groups.length > 0 || content.permissions.length > 0;
}

export function departmentSourcedContentEquals(
  left: DepartmentSourcedContent | null,
  right: DepartmentSourcedContent,
): boolean {
  if (!left) {
    return false;
  }
  if (left.groups.length !== right.groups.length || left.permissions.length !== right.permissions.length) {
    return false;
  }
  return (
    left.groups.every((group, index) => group.key === right.groups[index]?.key && group.name === right.groups[index]?.name) &&
    left.permissions.every(
      (permission, index) =>
        permission.permission === right.permissions[index]?.permission &&
        permission.scope === right.permissions[index]?.scope &&
        permission.permission_name === right.permissions[index]?.permission_name &&
        permission.scope_name === right.permissions[index]?.scope_name,
    )
  );
}

export function DepartmentSourcedGrants({
  identityKey,
  grant,
  status,
  isFetching,
  title,
  hint,
  loadingLabel,
}: {
  /** 被授权人(控制台)或空串(门户本人)。换人立刻清空; 换应用不改这个键, 走进出场过渡。 */
  identityKey: string;
  grant: DepartmentSourcedGrantLike | null;
  status: DepartmentSourcedNoticeStatus;
  isFetching: boolean;
  title: string;
  hint: string;
  loadingLabel: string;
}) {
  const [shownIdentity, setShownIdentity] = useState(identityKey);
  const [shown, setShown] = useState<DepartmentSourcedContent | null>(null);
  const [expanded, setExpanded] = useState(false);

  if (identityKey !== shownIdentity) {
    setShownIdentity(identityKey);
    setShown(null);
    setExpanded(false);
  } else if (status === "idle" || status === "error") {
    if (expanded) {
      setExpanded(false);
    }
  } else if (status === "success") {
    const next = departmentSourcedContent(grant);
    if (departmentSourcedContentHasItems(next)) {
      if (!departmentSourcedContentEquals(shown, next)) {
        setShown(next);
      }
    } else if (expanded) {
      setExpanded(false);
    }
  }

  const shouldOpen =
    status === "success" && shown !== null && departmentSourcedContentHasItems(departmentSourcedContent(grant));

  useEffect(() => {
    if (shouldOpen && !expanded) {
      setExpanded(true);
    }
  }, [expanded, shouldOpen]);

  const loadingStatus =
    isFetching ? (
      <p className="sr-only" role="status">
        {loadingLabel}
      </p>
    ) : null;

  if (!shown) {
    return loadingStatus;
  }

  return (
    <div
      className={cn(
        "department-sourced-grants",
        expanded && "department-sourced-grants--open",
        isFetching && "department-sourced-grants--fetching",
      )}
      aria-hidden={!expanded}
      inert={expanded ? undefined : true}
    >
      <div className="department-sourced-grants__body">
        <section className="department-sourced-grants__panel mt-5 rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5">
          <h3 className="text-xs font-semibold text-ink">{title}</h3>
          <p className="mt-1 text-xs leading-5 text-ink-faint">{hint}</p>
          <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-xs leading-5 text-ink-soft">
            {shown.groups.map((group) => (
              <li key={`group:${group.key}`}>{group.name}</li>
            ))}
            {shown.permissions.map((permission) => (
              <li key={`permission:${permission.permission}:${permission.scope}`}>
                {`${permission.permission_name} · ${permission.scope_name}`}
              </li>
            ))}
          </ul>
          {loadingStatus}
        </section>
      </div>
    </div>
  );
}

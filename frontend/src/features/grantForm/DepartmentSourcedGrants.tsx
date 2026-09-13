/**
 * 「来自组织授权」提示框: 直接授权页与员工申请表共用。
 *
 * 进出场走同一套高度 + 透明度 + 轻微位移过渡; 退出期间上一份内容保持挂载,
 * 过渡结束(wrapper 上 grid-template-rows / opacity 的 transitionend, 只处理一次)
 * 或时长+50ms 超时兜底后再卸掉, 避免收起后旧标题和列表永远留在 DOM(aria-hidden/inert)。
 * 退出中途再次展开会取消待执行的卸挂。换被授权人必须立刻卸掉, 不能把上一个人的组织授权留在这一格。
 */

import { useEffect, useRef, useState } from "react";

import { cn } from "../../lib/cn";

/** 与 department-sourced-grants.css 进出场时长对齐。 */
const EXIT_TRANSITION_MS = 200;
/** transitionend 缺席时(reduced-motion、零时长、jsdom)的卸挂兜底。 */
const EXIT_UNMOUNT_FALLBACK_MS = EXIT_TRANSITION_MS + 50;

const EXIT_TRANSITION_PROPERTIES = new Set(["grid-template-rows", "opacity"]);

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
  const wrapperRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    if (expanded || shown === null || shouldOpen) {
      return;
    }

    const wrapper = wrapperRef.current;
    let finished = false;
    const unmount = () => {
      if (finished) {
        return;
      }
      finished = true;
      setShown(null);
    };
    const onTransitionEnd = (event: TransitionEvent) => {
      if (event.target !== wrapper) {
        return;
      }
      if (!EXIT_TRANSITION_PROPERTIES.has(event.propertyName)) {
        return;
      }
      unmount();
    };

    wrapper?.addEventListener("transitionend", onTransitionEnd);
    const timeoutId = window.setTimeout(unmount, EXIT_UNMOUNT_FALLBACK_MS);
    return () => {
      finished = true;
      wrapper?.removeEventListener("transitionend", onTransitionEnd);
      window.clearTimeout(timeoutId);
    };
  }, [expanded, shown, shouldOpen]);

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
      ref={wrapperRef}
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

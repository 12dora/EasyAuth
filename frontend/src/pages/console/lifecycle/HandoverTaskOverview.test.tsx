import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { HandoverTaskDetail } from "../../../lib/domain";
import type { PersonRef } from "../../../lib/domain/person";
import { AssigneePanel, SubjectPanel } from "./HandoverTaskOverview";

const directoryPerson: PersonRef = {
  user_id: "u-admin",
  name: "李管理员",
  department: "捷发-安环部",
  account_kind: "directory",
  avatar_url: "",
};

const actorPerson: PersonRef = {
  user_id: "u-su",
  name: "王超管",
  department: "信息技术部",
  account_kind: "directory",
  avatar_url: "",
};

function task(patch: Partial<HandoverTaskDetail> = {}): HandoverTaskDetail {
  return {
    id: 1,
    kind: "offboard",
    status: "in_progress",
    generation: 1,
    subject: { user_id: "u-1", name: "张三", email: "z@example.com", department: "销售", status: "departed" },
    assignee: { user_id: "a1", name: "主管" },
    assignee_state: "manager",
    escalation_level: 0,
    escalation: {
      deadline: "2026-08-24T00:00:00Z",
      days_left: 9,
      level: 0,
      deferred_at: "2026-08-01T00:00:00Z",
      defer_history: [],
    },
    reason: "离职",
    created_at: "2026-07-01T09:00:00Z",
    created_by: "u-admin",
    created_by_person: null,
    actions: [],
    team_items: [],
    ...patch,
  };
}

describe("HandoverTaskOverview 人员展示", () => {
  test("创建人有 PersonRef 时展示姓名与部门", () => {
    render(<SubjectPanel task={task({ created_by_person: directoryPerson })} subjectName="张三" />);
    expect(screen.getByText("李管理员 · 捷发-安环部")).toBeVisible();
    expect(screen.queryByText("u-admin")).toBeNull();
  });

  test("创建人为 null 时回落原始 id", () => {
    render(<SubjectPanel task={task({ created_by: "system-actor", created_by_person: null })} subjectName="张三" />);
    expect(screen.getByText("system-actor")).toBeVisible();
  });

  test("顺延记录有 PersonRef 时展示姓名与部门, 否则回落 actor_id", () => {
    const withPerson = task({
      escalation: {
        deadline: "2026-08-24T00:00:00Z",
        days_left: 9,
        level: 0,
        deferred_at: "2026-08-01T00:00:00Z",
        defer_history: [
          {
            escalation_level: 0,
            actor_id: "u-su",
            actor_person: actorPerson,
            at: "2026-08-01T00:00:00Z",
            reason: "业务高峰顺延一次",
          },
        ],
      },
    });
    const { rerender } = render(
      <AssigneePanel
        task={withPerson}
        isLocalAdmin={false}
        claimPending={false}
        onDefer={() => undefined}
        onClaim={() => undefined}
      />,
    );
    expect(screen.getByText(/王超管 · 信息技术部/)).toBeVisible();
    expect(screen.getByText(/业务高峰顺延一次/)).toBeVisible();
    expect(screen.queryByText(/u-su/)).toBeNull();

    rerender(
      <AssigneePanel
        task={task({
          escalation: {
            deadline: "2026-08-24T00:00:00Z",
            days_left: 9,
            level: 0,
            deferred_at: "2026-08-01T00:00:00Z",
            defer_history: [
              {
                escalation_level: 0,
                actor_id: "unknown-actor",
                actor_person: null,
                at: "2026-08-01T00:00:00Z",
                reason: "业务高峰顺延一次",
              },
            ],
          },
        })}
        isLocalAdmin={false}
        claimPending={false}
        onDefer={() => undefined}
        onClaim={() => undefined}
      />,
    );
    expect(screen.getByText(/unknown-actor/)).toBeVisible();
  });
});

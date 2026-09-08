import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UserEvent } from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "../../components/antd/testing";
import type { PortalRequestCatalogView } from "../../pages/portal/hooks/accessRequestTypes";
import type { AccessGrantRow } from "../../lib/domain/accessGrantRow";
import {
  EMPTY_GRANT_DRAFT,
  GrantForm,
  buildGrantSubmission,
  grantDraftErrors,
  grantDraftFromCurrentGrant,
  grantDraftFromPolicy,
  grantDraftIsValid,
  parseCurrentGrantPayload,
} from "./index";
import type { GrantDraft } from "./index";

// antd 多选下拉 + 权限选择表格在 jsdom 下与其余控制台用例同一档。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const CATALOG: PortalRequestCatalogView = {
  apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "客户管理" }],
  approver_options: [],
  authorization_groups: [
    {
      id: 11,
      app_key: "crm",
      key: "sales",
      kind: "role",
      name: "销售",
      grants: [{ permission_key: "crm.customer.read", scope_key: "SELF" }],
    },
  ],
  permission_groups: [
    {
      id: 1,
      app_key: "crm",
      type: "group",
      key: "crm.customer",
      name: "客户管理",
      permissions: [
        {
          id: 101,
          app_key: "crm",
          key: "crm.customer.read",
          name: "查看客户",
          scopes: [{ key: "SELF", name: "本人" }],
        },
      ],
    },
  ],
  ungrouped_permissions: [],
};

const GROUP_DRAFT: GrantDraft = {
  ...EMPTY_GRANT_DRAFT,
  appKey: "crm",
  authorizationGroupKeys: ["sales"],
  reason: "新同事接手客户维护",
};

describe("授权草稿", () => {
  test("提交闸门要求应用在目录里、目标非空、说明非空", () => {
    expect(grantDraftIsValid(EMPTY_GRANT_DRAFT, CATALOG)).toBe(false);
    // 目录还没加载完就不放行, 不靠后端兜底。
    expect(grantDraftIsValid(GROUP_DRAFT, undefined)).toBe(false);
    expect(grantDraftIsValid({ ...GROUP_DRAFT, appKey: "unknown" }, CATALOG)).toBe(false);
    expect(grantDraftIsValid({ ...GROUP_DRAFT, authorizationGroupKeys: [] }, CATALOG)).toBe(false);
    expect(grantDraftIsValid({ ...GROUP_DRAFT, reason: "   " }, CATALOG)).toBe(false);
    expect(grantDraftIsValid(GROUP_DRAFT, CATALOG)).toBe(true);
    // 只选直接权限也是合法目标。
    expect(
      grantDraftIsValid(
        { ...GROUP_DRAFT, authorizationGroupKeys: [], selectedPermissionKeys: ['["crm.customer.read","SELF"]'] },
        CATALOG,
      ),
    ).toBe(true);
  });

  test("限时授权必须给一个未来的到期时间", () => {
    const timed: GrantDraft = { ...GROUP_DRAFT, grantType: "timed" };
    expect(grantDraftIsValid(timed, CATALOG)).toBe(false);
    expect(grantDraftIsValid({ ...timed, expiresAt: "2020-01-01T00:00" }, CATALOG)).toBe(false);
    expect(grantDraftIsValid({ ...timed, expiresAt: futureDatetimeLocal() }, CATALOG)).toBe(true);
  });

  test("载荷把选择键拆成权限与范围, 到期时间转成 ISO", () => {
    const expiresAt = futureDatetimeLocal();
    const submission = buildGrantSubmission({
      ...GROUP_DRAFT,
      selectedPermissionKeys: ['["crm.customer.read","SELF"]'],
      grantType: "timed",
      expiresAt,
      reason: "  新同事接手客户维护  ",
    });

    expect(submission).toEqual({
      app_key: "crm",
      authorization_group_keys: ["sales"],
      direct_grants: [{ permission: "crm.customer.read", scope: "SELF" }],
      grant_type: "timed",
      grant_expires_at: new Date(expiresAt).toISOString(),
      reason: "新同事接手客户维护",
    });
  });

  test("长期授权不带到期时间", () => {
    expect(buildGrantSubmission(GROUP_DRAFT).grant_expires_at).toBeNull();
  });

  test("非法草稿直接抛错, 不产出必被后端拒绝的载荷", () => {
    expect(() => buildGrantSubmission(EMPTY_GRANT_DRAFT)).toThrow(/应用/);
    expect(() => buildGrantSubmission({ ...GROUP_DRAFT, authorizationGroupKeys: [] })).toThrow(/授权组/);
    expect(() => buildGrantSubmission({ ...GROUP_DRAFT, reason: " " })).toThrow(/说明/);
    expect(() => buildGrantSubmission({ ...GROUP_DRAFT, grantType: "timed" })).toThrow(/到期时间/);
  });

  test("策略回填草稿后再构造载荷能拿回同一份策略, 秒与微秒都不丢", () => {
    // 后端用 datetime.isoformat() 序列化, 时间戳带秒与微秒; datetime-local 只有分钟精度,
    // 只改说明就提交绝不能把有效期悄悄提前。
    const policy = {
      app_key: "crm",
      authorization_groups: [{ key: "sales" }],
      permissions: [{ key: "crm.customer.read", scope: "SELF" }],
      grant_type: "timed" as const,
      expires_at: "2030-12-31T15:59:59.123456+00:00",
      reason: "销售部统一授权",
    };

    const draft = grantDraftFromPolicy(policy);
    expect(draft.appKey).toBe("crm");
    expect(draft.authorizationGroupKeys).toEqual(["sales"]);
    expect(draft.selectedPermissionKeys).toEqual(['["crm.customer.read","SELF"]']);
    expect(draft.grantType).toBe("timed");
    expect(draft.reason).toBe("销售部统一授权");
    expect(buildGrantSubmission(draft)).toEqual({
      app_key: "crm",
      authorization_group_keys: ["sales"],
      direct_grants: [{ permission: "crm.customer.read", scope: "SELF" }],
      grant_type: "timed",
      grant_expires_at: "2030-12-31T15:59:59.123456+00:00",
      reason: "销售部统一授权",
    });

    // 只改说明: 到期时间原样回传。
    expect(buildGrantSubmission({ ...draft, reason: "改一下说明" }).grant_expires_at).toBe(
      "2030-12-31T15:59:59.123456+00:00",
    );
  });

  test("改过到期时间控件后以控件值为准", () => {
    const draft = grantDraftFromPolicy({
      app_key: "crm",
      authorization_groups: [{ key: "sales" }],
      permissions: [],
      grant_type: "timed",
      expires_at: "2030-12-31T15:59:59.123456+00:00",
      reason: "销售部统一授权",
    });

    // GrantForm 在 onChange 里清空回填来源。
    const edited = { ...draft, expiresAt: "2031-01-31T10:30", expiresAtSource: "" };
    expect(buildGrantSubmission(edited).grant_expires_at).toBe(new Date("2031-01-31T10:30").toISOString());
  });

  test("长期策略回填后到期时间为空", () => {
    const draft = grantDraftFromPolicy({
      app_key: "crm",
      authorization_groups: [],
      permissions: [{ key: "crm.customer.read", scope: "SELF" }],
      grant_type: "permanent",
      expires_at: null,
      reason: "长期授权",
    });

    expect(draft.expiresAt).toBe("");
    expect(buildGrantSubmission(draft).grant_expires_at).toBeNull();
  });

  test("grantDraftErrors 逐项给出拦点与文案 key", () => {
    expect(grantDraftErrors(GROUP_DRAFT, undefined)).toEqual([
      { field: "catalog", messageKey: "grantForm.error.catalogUnavailable" },
    ]);
    expect(grantDraftErrors(EMPTY_GRANT_DRAFT, CATALOG)).toEqual([
      { field: "app", messageKey: "grantForm.error.appRequired" },
      { field: "target", messageKey: "grantForm.error.targetRequired" },
      { field: "reason", messageKey: "grantForm.error.reasonRequired" },
    ]);
    expect(grantDraftErrors({ ...GROUP_DRAFT, grantType: "timed" }, CATALOG)).toEqual([
      { field: "expiresAt", messageKey: "grantForm.error.expiresAtRequired" },
    ]);
    expect(
      grantDraftErrors({ ...GROUP_DRAFT, grantType: "timed", expiresAt: "2020-01-01T00:00" }, CATALOG),
    ).toEqual([{ field: "expiresAt", messageKey: "grantForm.expiresAtInvalid" }]);
    expect(grantDraftErrors(GROUP_DRAFT, CATALOG)).toEqual([]);
  });

  test("到期时间走到过去后同一份草稿不再合法", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    try {
      vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
      const draft: GrantDraft = {
        ...GROUP_DRAFT,
        grantType: "timed",
        expiresAt: "2030-01-01T09:00",
        expiresAtSource: "",
      };
      expect(grantDraftIsValid(draft, CATALOG)).toBe(true);

      vi.setSystemTime(new Date("2030-01-02T00:00:00Z"));
      expect(grantDraftErrors(draft, CATALOG)).toEqual([
        { field: "expiresAt", messageKey: "grantForm.expiresAtInvalid" },
      ]);
    } finally {
      vi.useRealTimers();
    }
  });

  test("期限与到期时间不匹配的策略直接抛错", () => {
    expect(() =>
      grantDraftFromPolicy({
        app_key: "crm",
        authorization_groups: [{ key: "sales" }],
        permissions: [],
        grant_type: "timed",
        expires_at: null,
        reason: "缺到期时间",
      }),
    ).toThrow(/到期时间/);
  });
});

describe("现有授权回填", () => {
  const CURRENT_GRANT: AccessGrantRow = {
    id: 6,
    version: 3,
    is_current: true,
    status: "active",
    user_id: "u-1",
    user_name: "张三",
    app_key: "crm",
    app_name: "CRM",
    app_alias: "客户管理",
    grant_type: "mixed",
    grant_expires_at: "2030-06-30T15:59:59.123456+00:00",
    authorization_groups: [
      { key: "sales", kind: "role", name: "销售", expires_at: null, source: "user" },
      { key: "audit", kind: "role", name: "审计", expires_at: null, source: "department" },
    ],
    direct_grants: [
      {
        permission: "crm.customer.read",
        permission_name: "查看客户",
        scope: "SELF",
        scope_name: "本人",
        expires_at: "2031-01-01T00:00:00+00:00",
        source: "user",
      },
      {
        permission: "crm.customer.export",
        permission_name: "导出客户",
        scope: "SELF",
        scope_name: "本人",
        expires_at: "2030-06-30T15:59:59.123456+00:00",
        source: "user",
      },
      {
        permission: "crm.report.view",
        permission_name: "查看报表",
        scope: "ALL",
        scope_name: "全部",
        expires_at: null,
        source: "department",
      },
    ],
    groups: [],
    grants: [],
  };

  test("只回填本人来源的成员关系, 期限取其中最早的到期时间", () => {
    const draft = grantDraftFromCurrentGrant(CURRENT_GRANT, { ...EMPTY_GRANT_DRAFT, reason: "补齐权限" });

    // 组织授权下发的审计组与报表权限不进草稿: 提交只替换本人来源的成员关系。
    expect(draft.appKey).toBe("crm");
    expect(draft.authorizationGroupKeys).toEqual(["sales"]);
    expect(draft.selectedPermissionKeys).toEqual([
      '["crm.customer.read","SELF"]',
      '["crm.customer.export","SELF"]',
    ]);
    expect(draft.grantType).toBe("timed");
    expect(draft.expiresAtSource).toBe("2030-06-30T15:59:59.123456+00:00");
    // 说明不回填: 每次授权都要写这一次的依据。
    expect(draft.reason).toBe("补齐权限");
    // 回填后原样提交, 秒与微秒都不丢。
    expect(buildGrantSubmission(draft).grant_expires_at).toBe("2030-06-30T15:59:59.123456+00:00");
  });

  test("本人来源成员关系全是长期时回填成长期草稿", () => {
    const draft = grantDraftFromCurrentGrant(
      {
        ...CURRENT_GRANT,
        direct_grants: CURRENT_GRANT.direct_grants.filter((item) => item.source === "department"),
      },
      EMPTY_GRANT_DRAFT,
    );

    expect(draft.authorizationGroupKeys).toEqual(["sales"]);
    expect(draft.selectedPermissionKeys).toEqual([]);
    expect(draft.grantType).toBe("permanent");
    expect(draft.expiresAt).toBe("");
    expect(draft.expiresAtSource).toBe("");
  });

  test("当前授权响应: null 表示没有生效授权, 形状不符直接抛错", () => {
    expect(parseCurrentGrantPayload({ grant: null })).toBeNull();
    expect(parseCurrentGrantPayload({ grant: CURRENT_GRANT })?.app_key).toBe("crm");
    expect(() => parseCurrentGrantPayload({})).toThrow(/grant/);
    expect(() => parseCurrentGrantPayload(null)).toThrow(/对象/);
  });
});

describe("GrantForm", () => {
  test("渲染目录里的应用, 选中应用后展示权限树", async () => {
    const user = userEvent.setup({ delay: null });
    renderForm();

    expect(screen.getByLabelText("应用")).toBeVisible();
    expect(screen.getByText("授权组")).toBeVisible();
    expect(screen.getByText("权限")).toBeVisible();
    // 未选应用时权限选择器是占位态, 表格还没有。
    expect(screen.queryByRole("table", { name: "权限选择" })).toBeNull();

    await user.selectOptions(screen.getByLabelText("应用"), "crm");

    const table = await screen.findByRole("table", { name: "权限选择" });
    expect(within(table).getByText("客户管理")).toBeVisible();
  });

  test("选中授权组会写回草稿", async () => {
    const user = userEvent.setup({ delay: null });
    const drafts: GrantDraft[] = [];
    renderForm((draft) => drafts.push(draft));

    await user.selectOptions(screen.getByLabelText("应用"), "crm");
    await user.click(await authorizationGroupOption(user, "销售"));

    await waitFor(() => expect(drafts.at(-1)?.authorizationGroupKeys).toEqual(["sales"]));
  });

  test("有效期切到限时才能填到期时间, 过去时间给出错误提示", async () => {
    const user = userEvent.setup({ delay: null });
    renderForm();

    const expiresAt = screen.getByLabelText("到期时间");
    expect(expiresAt).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("有效期"), "timed");
    expect(expiresAt).toBeEnabled();

    await user.type(expiresAt, "2020-01-01T08:00");
    expect(await screen.findByText("到期时间必须晚于当前时间。")).toBeVisible();
  });

  test("改动到期时间控件会清空回填来源", async () => {
    const user = userEvent.setup({ delay: null });
    const drafts: GrantDraft[] = [];
    renderForm((draft) => drafts.push(draft), {
      ...EMPTY_GRANT_DRAFT,
      appKey: "crm",
      grantType: "timed",
      expiresAt: "2030-12-31T23:59",
      expiresAtSource: "2030-12-31T15:59:59.123456+00:00",
    });

    await user.clear(screen.getByLabelText("到期时间"));
    await user.type(screen.getByLabelText("到期时间"), "2031-01-31T10:30");

    await waitFor(() => expect(drafts.at(-1)?.expiresAt).toBe("2031-01-31T10:30"));
    expect(drafts.at(-1)?.expiresAtSource).toBe("");
  });

  test("说明写回草稿", async () => {
    const user = userEvent.setup({ delay: null });
    const drafts: GrantDraft[] = [];
    renderForm((draft) => drafts.push(draft));

    await user.type(screen.getByLabelText("说明"), "补权限");

    await waitFor(() => expect(drafts.at(-1)?.reason).toBe("补权限"));
  });
});

function renderForm(onDraftChange?: (draft: GrantDraft) => void, initialDraft: GrantDraft = EMPTY_GRANT_DRAFT) {
  renderWithAntd(<GrantFormHarness onDraftChange={onDraftChange} initialDraft={initialDraft} />);
}

/** 草稿由调用方持有, 用例里用一个最小的受控壳子把它接起来。 */
function GrantFormHarness({
  onDraftChange,
  initialDraft,
}: {
  onDraftChange?: (draft: GrantDraft) => void;
  initialDraft: GrantDraft;
}) {
  const [draft, setDraft] = useState<GrantDraft>(initialDraft);
  return (
    <GrantForm
      catalog={CATALOG}
      catalogIsLoading={false}
      catalogErrorMessage=""
      draft={draft}
      onDraftChange={(next) => {
        setDraft(next);
        onDraftChange?.(next);
      }}
    />
  );
}

/** 「授权组」是 antd 多选下拉, 下拉是延迟挂载的 portal。 */
async function authorizationGroupOption(user: UserEvent, name: string): Promise<HTMLElement> {
  const combobox = screen.getByLabelText("授权组");
  const listId = combobox.getAttribute("aria-controls") ?? "";
  const mounted = document.getElementById(listId)?.closest(".ant-select-dropdown");
  if (mounted instanceof HTMLElement) {
    return within(mounted).getByTitle(name);
  }
  const selector = combobox.closest(".ant-select")?.querySelector(".ant-select-selector");
  if (!(selector instanceof HTMLElement)) {
    throw new Error("「授权组」不是 antd Select");
  }
  await user.click(selector);
  const dropdown = await waitFor(() => {
    const node = document.getElementById(listId)?.closest(".ant-select-dropdown");
    if (!(node instanceof HTMLElement)) {
      throw new Error("「授权组」的下拉没有出现");
    }
    return node;
  });
  return within(dropdown).getByTitle(name);
}

function futureDatetimeLocal(): string {
  const future = new Date(Date.now() + 24 * 60 * 60 * 1000);
  return new Date(future.getTime() - future.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { GrantPermissionsCell, type GrantPermissionsRow } from "./GrantPermissionsCell";
import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "../antd/testing";

vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const row: GrantPermissionsRow = {
  groups: [{ key: "auditor", name: "审计员" }],
  grants: [
    {
      source_type: "group",
      source_key: "auditor",
      permission_name: "查看账目",
      permission_name_en: "View ledger",
      scope_name: "全局",
      scope_name_en: "Global",
    },
    {
      source_type: "direct",
      source_key: null,
      permission_name: "导出发票",
      permission_name_en: "Export invoice",
      scope_name: "全局",
      scope_name_en: "Global",
    },
  ],
};

describe("GrantPermissionsCell", () => {
  test("没有权限时只显示条数, 不给浮层触发器", () => {
    renderWithAntd(<GrantPermissionsCell row={{ groups: [], grants: [] }} />);

    expect(screen.getByText("0 项权限")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  test("悬停后按来源分组列出权限明细", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithAntd(<GrantPermissionsCell row={row} />);

    await user.hover(screen.getByRole("button", { name: "2 项权限" }));

    await waitFor(() => {
      expect(screen.getByText("审计员")).toBeInTheDocument();
    });
    expect(screen.getByText("直接授权")).toBeInTheDocument();
    expect(screen.getByText("查看账目 · 全局")).toBeInTheDocument();
    expect(screen.getByText("导出发票 · 全局")).toBeInTheDocument();
  });
});

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { OrgTree } from "./OrgTree";
import type { OrgTreeNode } from "./OrgTree";
import { renderWithAntd } from "../../components/antd/testing";

const ROOT: OrgTreeNode = {
  dept_id: "1",
  name: "公司",
  children: [
    {
      dept_id: "12",
      name: "销售部",
      children: [{ dept_id: "121", name: "华东销售", children: [] }],
    },
    { dept_id: "13", name: "技术部", children: [] },
  ],
};

describe("OrgTree", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("展开的层级渲染出子部门, 行上不带人数", () => {
    renderTree();

    expect(screen.getByRole("tree", { name: "组织架构" })).toBeVisible();
    expect(treeItem("1")).toHaveAttribute("aria-expanded", "true");
    // 目录人数与"这条授权影响谁"不是一回事, 树上不再出现。
    expect(screen.queryByText(/人$/)).toBeNull();
    expect(treeItem("12")).toBeVisible();
    expect(treeItem("13")).toBeVisible();
    // 销售部未展开, 它的子部门不渲染。
    expect(treeItem("12")).toHaveAttribute("aria-expanded", "false");
    expect(queryTreeItem("121")).toBeNull();
    // 叶子节点没有展开状态。
    expect(treeItem("13")).not.toHaveAttribute("aria-expanded");
  });

  test("点整行既选中该部门, 又就地展开/收起", async () => {
    const user = userEvent.setup();
    renderTree();

    await user.click(screen.getByText("销售部"));

    expect(treeItem("12")).toHaveAttribute("aria-selected", "true");
    expect(treeItem("12")).toHaveAttribute("aria-expanded", "true");
    expect(treeItem("121")).toBeVisible();

    // 再点一次同一行: 保持选中, 收起子部门。
    await user.click(screen.getByText("销售部"));

    expect(treeItem("12")).toHaveAttribute("aria-selected", "true");
    expect(treeItem("12")).toHaveAttribute("aria-expanded", "false");
    await waitFor(() => expect(queryTreeItem("121")).toBeNull());
  });

  test("点叶子部门只选中, 不影响其它层级的展开态", async () => {
    const user = userEvent.setup();
    renderTree();

    await user.click(screen.getByText("技术部"));

    expect(treeItem("13")).toHaveAttribute("aria-selected", "true");
    expect(treeItem("13")).not.toHaveAttribute("aria-expanded");
    expect(treeItem("1")).toHaveAttribute("aria-expanded", "true");
  });

  test("点三角展开与收起切换 aria-expanded 并挂载/卸载子部门", async () => {
    const user = userEvent.setup();
    renderTree();

    await user.click(screen.getByRole("button", { name: "展开 销售部" }));

    expect(treeItem("12")).toHaveAttribute("aria-expanded", "true");
    expect(treeItem("121")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "收起 销售部" }));

    expect(treeItem("12")).toHaveAttribute("aria-expanded", "false");
    // 退场动画期间子部门仍挂载, 动画结束才卸载。
    await waitFor(() => expect(queryTreeItem("121")).toBeNull());
  });

  test("方向键在树内移动, 右键展开、左键收起, 回车选中", async () => {
    const user = userEvent.setup();
    renderTree();

    await user.tab();
    expect(treeItem("1")).toHaveFocus();

    await user.keyboard("{ArrowDown}");
    expect(treeItem("12")).toHaveFocus();

    await user.keyboard("{ArrowRight}");
    expect(treeItem("12")).toHaveAttribute("aria-expanded", "true");

    // 已展开时右键进入首个子部门。
    await user.keyboard("{ArrowRight}");
    expect(treeItem("121")).toHaveFocus();

    // 叶子节点左键回到父节点, 再左键收起父节点。
    await user.keyboard("{ArrowLeft}");
    expect(treeItem("12")).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(treeItem("12")).toHaveAttribute("aria-expanded", "false");

    await user.keyboard("{ArrowDown}");
    expect(treeItem("13")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(treeItem("12")).toHaveFocus();

    await user.keyboard("{Enter}");
    expect(treeItem("12")).toHaveAttribute("aria-selected", "true");
    expect(treeItem("1")).toHaveAttribute("aria-selected", "false");
  });

  test("鼠标点开三角后, 方向键与回车作用在刚点的那一行", async () => {
    const user = userEvent.setup();
    renderTree();

    await user.click(screen.getByRole("button", { name: "展开 销售部" }));
    expect(treeItem("12")).toHaveFocus();

    // 左键收起的必须是销售部, 不能落回上一次记录的公司。
    await user.keyboard("{ArrowLeft}");
    expect(treeItem("12")).toHaveAttribute("aria-expanded", "false");
    expect(treeItem("1")).toHaveAttribute("aria-expanded", "true");

    await user.keyboard("{Enter}");
    expect(treeItem("12")).toHaveAttribute("aria-selected", "true");
    expect(treeItem("1")).toHaveAttribute("aria-selected", "false");
  });

  test("鼠标点行选中后, 方向键从该行继续移动", async () => {
    const user = userEvent.setup();
    renderTree();

    await user.click(screen.getByText("技术部"));
    expect(treeItem("13")).toHaveFocus();
    expect(treeItem("13")).toHaveAttribute("aria-selected", "true");

    await user.keyboard("{ArrowUp}");
    expect(treeItem("12")).toHaveFocus();
  });

  test("搜索命中时自动展开祖先, 未命中的分支隐藏", () => {
    renderTree({ filter: "华东" });

    expect(treeItem("12")).toHaveAttribute("aria-expanded", "true");
    expect(treeItem("121")).toBeVisible();
    expect(queryTreeItem("13")).toBeNull();
  });

  test("labelFor 决定行文案、无障碍名与过滤口径", async () => {
    const user = userEvent.setup();
    const namelessRoot: OrgTreeNode = { ...ROOT, name: "" };

    renderTree({ root: namelessRoot, labelFor: (node) => node.name || "全公司" });

    expect(screen.getByRole("treeitem", { name: /全公司/ })).toBeVisible();
    expect(screen.getByRole("button", { name: "收起 全公司" })).toBeVisible();

    // 过滤按同一份文案走: 输入兜底名也能命中根部门。
    await user.click(screen.getByRole("button", { name: "收起 全公司" }));
    expect(treeItem("1")).toHaveAttribute("aria-expanded", "false");
  });

  test("按 labelFor 的文案过滤", () => {
    const namelessRoot: OrgTreeNode = { ...ROOT, name: "" };

    renderTree({ root: namelessRoot, labelFor: (node) => node.name || "全公司", filter: "全公司" });

    expect(screen.getByRole("treeitem", { name: /全公司/ })).toBeVisible();
    expect(queryTreeItem("12")).toBeNull();
  });

  test("搜索无命中时给出空文案", () => {
    renderTree({ filter: "不存在的部门" });

    expect(screen.getByText("没有匹配的部门")).toBeVisible();
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
  });

  test("prefers-reduced-motion 下展开收起仍然可用", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }));
    const user = userEvent.setup();
    renderTree();

    await user.click(screen.getByRole("button", { name: "展开 销售部" }));
    expect(treeItem("121")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "收起 销售部" }));
    await waitFor(() => expect(queryTreeItem("121")).toBeNull());
  });
});

function renderTree({
  filter = "",
  root = ROOT,
  labelFor,
}: { filter?: string; root?: OrgTreeNode; labelFor?: (node: OrgTreeNode) => string } = {}) {
  renderWithAntd(<TreeHarness filter={filter} root={root} labelFor={labelFor} />);
}

/** OrgTree 是受控组件; 用例里由这层壳持有选中与展开状态。 */
function TreeHarness({
  filter,
  root,
  labelFor,
}: {
  filter: string;
  root: OrgTreeNode;
  labelFor?: (node: OrgTreeNode) => string;
}) {
  const [selectedDeptId, setSelectedDeptId] = useState("1");
  const [expandedDeptIds, setExpandedDeptIds] = useState<string[]>(["1"]);

  return (
    <OrgTree
      root={root}
      labelFor={labelFor}
      selectedDeptId={selectedDeptId}
      expandedDeptIds={expandedDeptIds}
      onSelect={setSelectedDeptId}
      onExpandedChange={setExpandedDeptIds}
      filter={filter}
    />
  );
}

function treeItem(deptId: string): HTMLElement {
  const item = queryTreeItem(deptId);
  if (!item) {
    throw new Error(`树里没有部门 ${deptId}`);
  }
  return item;
}

function queryTreeItem(deptId: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[role="treeitem"][data-dept-id="${deptId}"]`);
}

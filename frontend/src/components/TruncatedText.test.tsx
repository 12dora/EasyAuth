import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { TruncatedText } from "./TruncatedText";
import { renderWithAntd } from "./antd/testing";

function mockLayout(element: HTMLElement, scrollWidth: number, clientWidth: number) {
  Object.defineProperty(element, "scrollWidth", { configurable: true, get: () => scrollWidth });
  Object.defineProperty(element, "clientWidth", { configurable: true, get: () => clientWidth });
}

function visibleTooltip(): HTMLElement | null {
  return document.querySelector(".ant-tooltip:not(.ant-tooltip-hidden)");
}

describe("TruncatedText", () => {
  test("未截断时不展示 Tooltip", async () => {
    const user = userEvent.setup();
    renderWithAntd(<TruncatedText text="捷发-安环部" />);

    const node = screen.getByText("捷发-安环部");
    mockLayout(node, 40, 80);
    await user.hover(node);

    expect(visibleTooltip()).toBeNull();
  });

  test("实际截断时 Tooltip 展示全文", async () => {
    const user = userEvent.setup();
    renderWithAntd(<TruncatedText text="捷发科技-安全管理部-安环组" />);

    const node = screen.getByText("捷发科技-安全管理部-安环组");
    mockLayout(node, 200, 80);
    await user.hover(node);

    await waitFor(() => expect(visibleTooltip()).not.toBeNull());
    expect(visibleTooltip()).toHaveTextContent("捷发科技-安全管理部-安环组");
  });

  test("文案变化时关闭 Tooltip, 下次悬停重新测量", async () => {
    const user = userEvent.setup();
    const { rerender } = renderWithAntd(<TruncatedText text="捷发科技-安全管理部-安环组" />);

    const longNode = screen.getByText("捷发科技-安全管理部-安环组");
    mockLayout(longNode, 200, 80);
    await user.hover(longNode);
    await waitFor(() => expect(visibleTooltip()).not.toBeNull());

    rerender(<TruncatedText text="捷发-安环部" />);
    await waitFor(() => expect(visibleTooltip()).toBeNull());

    const shortNode = screen.getByText("捷发-安环部", { selector: "span.truncate" });
    mockLayout(shortNode, 40, 80);
    await user.hover(shortNode);
    expect(visibleTooltip()).toBeNull();
  });

  test("指针在 data-tooltip-child 内时不打开溢出 Tooltip", async () => {
    const user = userEvent.setup();
    renderWithAntd(
      <TruncatedText text="张三, 李四" title={"张三 · 安环部\n李四 · 财务部"}>
        <span data-tooltip-child="">张三</span>
        {", "}
        <span data-tooltip-child="">李四</span>
      </TruncatedText>,
    );

    const wrapper = screen.getByText("张三").closest(".truncate");
    expect(wrapper).toBeInstanceOf(HTMLElement);
    mockLayout(wrapper as HTMLElement, 200, 80);

    await user.hover(screen.getByText("张三"));
    expect(visibleTooltip()).toBeNull();
  });

  test("指针在子节点外且已截断时打开溢出 Tooltip", async () => {
    renderWithAntd(
      <TruncatedText text="张三, 李四" title="张三 · 安环部">
        <span data-tooltip-child="">张三</span>
        {", "}
        <span data-tooltip-child="">李四</span>
      </TruncatedText>,
    );

    const wrapper = screen.getByText("张三").closest(".truncate");
    expect(wrapper).toBeInstanceOf(HTMLElement);
    mockLayout(wrapper as HTMLElement, 200, 80);

    fireEvent.mouseOver(wrapper as HTMLElement);
    await waitFor(() => expect(visibleTooltip()).not.toBeNull());
    expect(visibleTooltip()).toHaveTextContent("张三 · 安环部");
  });

  test("从空白处移入 data-tooltip-child 时关掉溢出 Tooltip", async () => {
    renderWithAntd(
      <TruncatedText text="张三, 李四">
        <span data-tooltip-child="">张三</span>
        {", "}
        <span data-tooltip-child="">李四</span>
      </TruncatedText>,
    );

    const child = screen.getByText("张三");
    const wrapper = child.closest(".truncate");
    expect(wrapper).toBeInstanceOf(HTMLElement);
    mockLayout(wrapper as HTMLElement, 200, 80);

    fireEvent.mouseOver(wrapper as HTMLElement);
    await waitFor(() => expect(visibleTooltip()).not.toBeNull());

    fireEvent.mouseOver(child);
    await waitFor(() => expect(visibleTooltip()).toBeNull());
  });

  test("isChildTarget 为真时忽略 mouseenter, 不打开溢出 Tooltip", () => {
    renderWithAntd(
      <TruncatedText
        text="abcdefghijklmnop"
        isChildTarget={(event) => event.target instanceof HTMLElement && event.target.dataset.role === "inner"}
      >
        <span data-role="inner">abcdefghijklmnop</span>
      </TruncatedText>,
    );

    const inner = screen.getByText("abcdefghijklmnop");
    const wrapper = inner.closest(".truncate");
    expect(wrapper).toBeInstanceOf(HTMLElement);
    mockLayout(wrapper as HTMLElement, 200, 80);

    fireEvent.mouseOver(inner);
    expect(visibleTooltip()).toBeNull();
  });
});

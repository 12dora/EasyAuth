import { screen, waitFor } from "@testing-library/react";
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
});

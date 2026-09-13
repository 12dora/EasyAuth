import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { Translator } from "../../../lib/status";
import { activeStatusColumn, statusColumn } from "./status";

const t = ((key: string) => {
  if (key === "common.enabled") {
    return "启用";
  }
  if (key === "common.disabled") {
    return "停用";
  }
  return key;
}) as Translator;

describe("statusColumn plain", () => {
  test("plain 渲染本地化文案为纯文本, 不画 Badge", () => {
    const column = statusColumn<{ status: string }>({
      key: "status",
      title: "配置",
      plain: true,
      options: [{ value: "ready", label: "就绪", tone: "evergreen" }],
    });
    render(<>{column.render?.("ready", { status: "ready" }, 0)}</>);

    const label = screen.getByText("就绪");
    expect(label.tagName).toBe("SPAN");
    expect(label).not.toHaveClass("tracking-caps-wide", "font-mono", "uppercase");
  });

  test("默认仍渲染 Badge", () => {
    const column = statusColumn<{ status: string }>({
      key: "status",
      title: "配置",
      options: [{ value: "ready", label: "就绪", tone: "evergreen" }],
    });
    render(<>{column.render?.("ready", { status: "ready" }, 0)}</>);

    expect(screen.getByText("就绪")).toHaveClass("tracking-caps-wide", "font-mono", "uppercase");
  });

  test("plain 时空值仍为 -, 筛选仍在", () => {
    const column = statusColumn<{ status: string }>({
      key: "status",
      title: "配置",
      plain: true,
      options: [{ value: "ready", label: "就绪" }],
    });
    expect(column.render?.("", { status: "" }, 0)).toBe("-");
    expect(column.filters).toEqual([{ text: "就绪", value: "ready" }]);
  });
});

describe("activeStatusColumn plain", () => {
  test("plain 传给单元格, 启用文案不是 Badge", () => {
    const column = activeStatusColumn<{ is_active: boolean }>({
      t,
      getActive: (row) => row.is_active,
      plain: true,
    });
    render(<>{column.render?.(true, { is_active: true }, 0)}</>);

    const label = screen.getByText("启用");
    expect(label.tagName).toBe("SPAN");
    expect(label).not.toHaveClass("tracking-caps-wide", "font-mono");
  });
});

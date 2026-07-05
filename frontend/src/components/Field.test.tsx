import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { Field, TextInput } from "./Field";

describe("Field", () => {
  test("包裹原生控件时用 label htmlFor 关联控件(FF-10)", () => {
    render(
      <Field label="应用名称" hint="唯一标识">
        <TextInput />
      </Field>,
    );

    const input = screen.getByLabelText("应用名称");
    expect(input.tagName).toBe("INPUT");
    const label = screen.getByText("应用名称");
    expect(label.tagName).toBe("LABEL");
    expect(label).toHaveAttribute("for", input.id);
    expect(input.id).toBeTruthy();
    // hint 通过 aria-describedby 关联到控件。
    expect(input.getAttribute("aria-describedby")).toContain(`${input.id}-hint`);
  });

  test("as=group 时用 role=group + aria-labelledby, 不产生悬空 htmlFor(FF-10)", () => {
    render(
      <Field as="group" label="审批人">
        <div data-testid="custom-control">自定义控件</div>
      </Field>,
    );

    const group = screen.getByRole("group");
    expect(group).toBeInTheDocument();
    const labelledBy = group.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    const labelNode = document.getElementById(labelledBy as string);
    expect(labelNode).not.toBeNull();
    expect(labelNode).toHaveTextContent("审批人");
    // 分组模式不得渲染带 htmlFor 的 <label>(否则指向不存在的控件)。
    expect(document.querySelector("label[for]")).toBeNull();
    expect(group).toContainElement(screen.getByTestId("custom-control"));
  });
});

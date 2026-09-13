import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { avatarInitials, PersonAvatar } from "./PersonAvatar";

describe("avatarInitials", () => {
  test("中日韩姓名取第一个字", () => {
    expect(avatarInitials("张三")).toBe("张");
    expect(avatarInitials("胡玉琴A")).toBe("胡");
    expect(avatarInitials("田中")).toBe("田");
  });

  test("拉丁姓名取首字母, 多词取首尾", () => {
    expect(avatarInitials("Alice")).toBe("A");
    expect(avatarInitials("Alice Smith")).toBe("AS");
    expect(avatarInitials("Jean Luc Picard")).toBe("JP");
  });

  test("空姓名不伪造字母", () => {
    expect(avatarInitials("")).toBe("");
    expect(avatarInitials("   ")).toBe("");
  });
});

describe("PersonAvatar", () => {
  test("https 与同源路径渲染照片", () => {
    const { rerender } = render(
      <PersonAvatar name="张三" avatarUrl="https://cdn.example.com/u.png" size={24} alt="张三 的头像" />,
    );
    expect(screen.getByRole("img", { name: "张三 的头像" })).toHaveAttribute("src", "https://cdn.example.com/u.png");
    expect(screen.getByRole("img")).toHaveAttribute("width", "24");

    rerender(<PersonAvatar name="张三" avatarUrl="/media/avatars/alice.png" size={32} alt="张三 的头像" />);
    expect(screen.getByRole("img")).toHaveAttribute("src", "/media/avatars/alice.png");
    expect(screen.getByRole("img")).toHaveAttribute("width", "32");
  });

  test("白名单 SVG data URL 渲染照片", () => {
    const src = "data:image/svg+xml;base64,PHN2Zy8+";
    render(<PersonAvatar name="张三" avatarUrl={src} size={20} alt="张三 的头像" />);

    const photo = screen.getByRole("img", { name: "张三 的头像" });
    expect(photo).toHaveAttribute("data-person-avatar", "photo");
    expect(photo).toHaveAttribute("src", src);
  });

  test("不安全的 data:/http:/javascript: 与空值回落为首字母, 中文取首字", () => {
    const { rerender } = render(
      <PersonAvatar name="张三" avatarUrl="data:text/html,alert(1)" size={20} />,
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("张")).toBeVisible();

    rerender(<PersonAvatar name="张三" avatarUrl="javascript:alert(1)" size={20} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("张")).toBeVisible();

    rerender(<PersonAvatar name="Alice Smith" avatarUrl="" size={20} />);
    expect(screen.getByText("AS")).toBeVisible();
  });

  test("照片加载失败时保持失败态并回落为首字母", () => {
    const missing = "https://cdn.example.com/missing.png";
    const { rerender } = render(
      <PersonAvatar name="张三" avatarUrl={missing} size={24} alt="张三 的头像" />,
    );
    fireEvent.error(screen.getByRole("img", { name: "张三 的头像" }));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("张")).toBeVisible();

    rerender(<PersonAvatar name="张三" avatarUrl={missing} size={24} alt="张三 的头像" />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("张")).toBeVisible();

    rerender(
      <PersonAvatar name="张三" avatarUrl="https://cdn.example.com/ok.png" size={24} alt="张三 的头像" />,
    );
    expect(screen.getByRole("img", { name: "张三 的头像" })).toHaveAttribute(
      "src",
      "https://cdn.example.com/ok.png",
    );
  });

  test("空姓名渲染中性占位符, 不留下空白圆", () => {
    const { rerender } = render(<PersonAvatar name="" size={24} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("?")).toBeVisible();

    rerender(<PersonAvatar name="   " size={20} />);
    expect(screen.getByText("?")).toBeVisible();
  });
});

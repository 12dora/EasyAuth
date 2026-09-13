import { describe, expect, test } from "vitest";

import { safeAvatarUrl } from "./avatarUrl";

describe("safeAvatarUrl", () => {
  test("接受 https 绝对地址与同源相对路径", () => {
    expect(safeAvatarUrl("https://cdn.example.com/u.png")).toBe("https://cdn.example.com/u.png");
    expect(safeAvatarUrl("/media/avatars/alice.png")).toBe("/media/avatars/alice.png");
  });

  test("空值与空白视为缺失", () => {
    expect(safeAvatarUrl("")).toBe("");
    expect(safeAvatarUrl("   ")).toBe("");
    expect(safeAvatarUrl(undefined)).toBe("");
    expect(safeAvatarUrl(null)).toBe("");
  });

  test("接受白名单内联图", () => {
    const svg = "data:image/svg+xml;base64,PHN2Zy8+";
    const png = "data:image/png;base64,iVBORw0KGgo=";
    const jpeg = "data:image/jpeg;base64,/9j/4AAQ=";
    const webp = "data:image/webp;base64,UklGRg==";
    expect(safeAvatarUrl(svg)).toBe(svg);
    expect(safeAvatarUrl(png)).toBe(png);
    expect(safeAvatarUrl(jpeg)).toBe(jpeg);
    expect(safeAvatarUrl(webp)).toBe(webp);
  });

  test("拒绝非白名单 data: 与其它危险地址", () => {
    expect(safeAvatarUrl("data:text/html,alert(1)")).toBe("");
    expect(safeAvatarUrl("data:image/svg+xml;utf8,<svg/>")).toBe("");
    expect(safeAvatarUrl("data:image/svg+xml;base64,PHN2Zy8+;foo")).toBe("");
    expect(safeAvatarUrl("DATA:image/png;base64,iVBORw0KGgo=")).toBe("");
    expect(safeAvatarUrl("http://cdn.example.com/u.png")).toBe("");
    expect(safeAvatarUrl("javascript:alert(1)")).toBe("");
    expect(safeAvatarUrl("//cdn.example.com/u.png")).toBe("");
    expect(safeAvatarUrl("/media\\avatars\\alice.png")).toBe("");
  });

  test("内联图超长或体含非法字符视为缺失", () => {
    const prefix = "data:image/png;base64,";
    const atCap = prefix + "A".repeat(16384 - prefix.length);
    expect(safeAvatarUrl(atCap)).toBe(atCap);
    expect(safeAvatarUrl(prefix + "A".repeat(16384 - prefix.length + 1))).toBe("");
    expect(safeAvatarUrl("data:image/png;base64,abc def")).toBe("");
    expect(safeAvatarUrl("data:image/png;base64,")).toBe("");
  });
});

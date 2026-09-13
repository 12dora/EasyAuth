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

  test("data:/http:/javascript:/协议相对地址视为缺失", () => {
    expect(safeAvatarUrl("data:image/svg+xml;base64,PHN2Zy8+")).toBe("");
    expect(safeAvatarUrl("http://cdn.example.com/u.png")).toBe("");
    expect(safeAvatarUrl("javascript:alert(1)")).toBe("");
    expect(safeAvatarUrl("//cdn.example.com/u.png")).toBe("");
    expect(safeAvatarUrl("/media\\avatars\\alice.png")).toBe("");
  });
});

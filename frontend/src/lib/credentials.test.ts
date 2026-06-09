import { describe, expect, test } from "vitest";

import { credentialDisablePathSegment } from "./credentials";

describe("credentialDisablePathSegment", () => {
  test("把前端凭据 kind 映射为后端禁用路径片段", () => {
    expect(credentialDisablePathSegment("static_token")).toBe("static-tokens");
    expect(credentialDisablePathSegment("oauth_client")).toBe("oauth-clients");
  });
});

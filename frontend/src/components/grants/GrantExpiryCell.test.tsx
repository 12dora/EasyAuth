import { screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { GrantExpiryCell } from "./GrantExpiryCell";
import { renderWithAntd } from "../antd/testing";

describe("GrantExpiryCell", () => {
  test("长期授权只显示期限标签, 不显示时刻", () => {
    renderWithAntd(<GrantExpiryCell grantType="permanent" expiresAt={null} />);

    expect(screen.getByText("长期")).toBeInTheDocument();
  });

  test("限时授权显示到期时刻", () => {
    renderWithAntd(<GrantExpiryCell grantType="timed" expiresAt="2026-08-01T10:00:00Z" />);

    expect(screen.getByText(/2026/)).toBeInTheDocument();
  });

  test("混合期限在时刻后补上期限标签", () => {
    renderWithAntd(<GrantExpiryCell grantType="mixed" expiresAt="2026-08-01T10:00:00Z" />);

    expect(screen.getByText(/2026.*（混合期限）/)).toBeInTheDocument();
  });
});

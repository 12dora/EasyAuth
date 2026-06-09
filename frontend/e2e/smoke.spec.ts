import { expect, test } from "@playwright/test";

test("控制台 React shell 可以加载", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("EasyAuth").first()).toBeVisible();
  await expect(page.getByRole("navigation").getByText("应用")).toBeVisible();
});

test("控制台和门户深链可以直接打开", async ({ page }) => {
  await page.goto("/console/operations/access-requests");

  await expect(page.getByRole("navigation").getByText("申请运营")).toBeVisible();
  await expect(page.getByTestId("route-transition")).toHaveAttribute(
    "data-route-pathname",
    "/console/operations/access-requests",
  );

  await page.goto("/portal/request");

  await expect(page.getByRole("navigation").getByText("申请权限")).toBeVisible();
  await expect(page.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/request");
});

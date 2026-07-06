import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import { describe, expect, test } from "vitest";

// FF-9 回归护栏: 以下组件的用户可见中文必须全部走 i18n t(), 组件代码里不得再残留中文字面量。
// 注释里的中文仍需保留(AGENTS.md 约定), 因此断言前先剥离注释再校验。
const CURRENT_DIR = dirname(fileURLToPath(import.meta.url));
const SRC_DIR = resolve(CURRENT_DIR, "..");

const GUARDED_FILES = [
  "pages/portal/PortalPage.tsx",
  "pages/portal/components/AccessRequestForm.tsx",
  "pages/portal/components/PortalApprovalsSection.tsx",
  "components/ApprovalDecisionDialog.tsx",
  "pages/console/OperationsPage.tsx",
  "pages/console/ConsoleAppWorkspace.tsx",
  "pages/console/ConsoleSettingsPage.tsx",
  "pages/console/ConsoleTeamList.tsx",
  "pages/console/ConsoleTeamDetail.tsx",
  "pages/console/ApprovalTemplatesPage.tsx",
  "pages/console/ApprovalInstancesPage.tsx",
  "pages/console/workspace/tabs/WebhookTab.tsx",
  "pages/console/workspace/tabs/MatrixTab.tsx",
  "pages/console/workspace/tabs/CatalogTab.tsx",
  "pages/console/workspace/tabs/RulesTab.tsx",
  "pages/console/workspace/tabs/CredentialsTab.tsx",
  "pages/console/workspace/tabs/OverviewTab.tsx",
  "pages/console/workspace/tabs/QueryTestTab.tsx",
  "components/SecretDialog.tsx",
  "pages/console/workspace/credentials/CreateCredentialForm.tsx",
  "pages/console/lifecycle/ConsolePeopleList.tsx",
  "pages/console/lifecycle/HandoverTaskList.tsx",
  "pages/console/lifecycle/HandoverTaskDetail.tsx",
  "pages/console/lifecycle/HandoverWizard.tsx",
  "pages/console/lifecycle/OnboardingPage.tsx",
] as const;

const CJK_IDEOGRAPH = /[一-鿿]/;

function stripComments(source: string): string {
  // 先去块注释 /* ... */, 再去整行 // 注释(仅整行以避免破坏 URL 里的 https://)。
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

describe("FF-9 无硬编码中文护栏", () => {
  test.each(GUARDED_FILES)("%s 剥离注释后不含 CJK 字符", (relativePath) => {
    const source = readFileSync(resolve(SRC_DIR, relativePath), "utf8");
    const code = stripComments(source);
    expect(CJK_IDEOGRAPH.test(code)).toBe(false);
  });
});

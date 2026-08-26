import { zhCN as commonZhCN, en as commonEn } from "./messages/common";
import { zhCN as selectorZhCN, en as selectorEn } from "./messages/selector";
import { zhCN as consoleOverviewZhCN, en as consoleOverviewEn } from "./messages/console-overview";
import { zhCN as consoleConnectorZhCN, en as consoleConnectorEn } from "./messages/console-connector";
import { zhCN as consoleIntegrationZhCN, en as consoleIntegrationEn } from "./messages/console-integration";
import { zhCN as consoleAccessZhCN, en as consoleAccessEn } from "./messages/console-access";
import { zhCN as handoverPortalZhCN, en as handoverPortalEn } from "./messages/handover-portal";
import { zhCN as handoverConsoleZhCN, en as handoverConsoleEn } from "./messages/handover-console";
import { zhCN as handoverWizardZhCN, en as handoverWizardEn } from "./messages/handover-wizard";
import { zhCN as wizardZhCN, en as wizardEn } from "./messages/wizard";
import { zhCN as portalZhCN, en as portalEn } from "./messages/portal";
import { zhCN as settingsZhCN, en as settingsEn } from "./messages/settings";
import { zhCN as onboardingZhCN, en as onboardingEn } from "./messages/onboarding";
import { zhCN as approvalsZhCN, en as approvalsEn } from "./messages/approvals";
import { zhCN as peopleZhCN, en as peopleEn } from "./messages/people";


export type Locale = "zh-CN" | "en";

export const SUPPORTED_LOCALES: Locale[] = ["zh-CN", "en"];

/**
 * zh-CN 是消息目录的事实源；en 通过 Record<MessageKey, string> 强制键集合一致，
 * 缺失或多余的键都会在编译期报错。
 *
 * 消息条目按顶层命名空间拆分到 ./messages/*.ts，本文件只做聚合；
 * 每个分片内部同样用 Record<keyof typeof zhCN, string> 保证该命名空间的中英键一一对应。
 */
const zhCN = {
  ...commonZhCN,
  ...selectorZhCN,
  ...consoleOverviewZhCN,
  ...consoleConnectorZhCN,
  ...consoleIntegrationZhCN,
  ...consoleAccessZhCN,
  ...handoverPortalZhCN,
  ...handoverConsoleZhCN,
  ...handoverWizardZhCN,
  ...wizardZhCN,
  ...portalZhCN,
  ...settingsZhCN,
  ...onboardingZhCN,
  ...approvalsZhCN,
  ...peopleZhCN,
} as const;

export type MessageKey = keyof typeof zhCN;

const en: Record<MessageKey, string> = {
  ...commonEn,
  ...selectorEn,
  ...consoleOverviewEn,
  ...consoleConnectorEn,
  ...consoleIntegrationEn,
  ...consoleAccessEn,
  ...handoverPortalEn,
  ...handoverConsoleEn,
  ...handoverWizardEn,
  ...wizardEn,
  ...portalEn,
  ...settingsEn,
  ...onboardingEn,
  ...approvalsEn,
  ...peopleEn,
};

export const MESSAGES: Record<Locale, Record<MessageKey, string>> = {
  "zh-CN": zhCN,
  en,
};

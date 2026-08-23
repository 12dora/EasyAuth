import type { WizardStep, WizardStepDescriptor } from "./types";

export const WIZARD_STEPS: WizardStepDescriptor[] = [
  { key: "basics", labelKey: "wizard.step.basics" },
  { key: "catalog", labelKey: "wizard.step.catalog" },
  { key: "authz", labelKey: "wizard.step.authz" },
  { key: "credential", labelKey: "wizard.step.credential" },
  { key: "verify", labelKey: "wizard.step.verify" },
  { key: "done", labelKey: "wizard.step.done" },
];

/** URL 上的 step 参数不可信: 未知步骤, 或缺少 app_key 时的非首步, 一律回落到 basics。 */
export function resolveActiveStep(requestedStep: WizardStep, appKey: string): WizardStep {
  const stepIsKnown = WIZARD_STEPS.some((step) => step.key === requestedStep);
  return !stepIsKnown || (!appKey && requestedStep !== "basics") ? "basics" : requestedStep;
}

export function findStepIndex(step: WizardStep): number {
  return WIZARD_STEPS.findIndex((item) => item.key === step);
}

export function buildWizardStepQuery(step: WizardStep, appKey: string): string {
  const params = new URLSearchParams();
  if (appKey) {
    params.set("app_key", appKey);
  }
  params.set("step", step);
  return params.toString();
}

export function isStepReachable(
  step: WizardStep,
  stepIndex: number,
  { appKey, navigationLocked, doneBlocked }: { appKey: string; navigationLocked: boolean; doneBlocked: boolean },
): boolean {
  return (stepIndex === 0 || Boolean(appKey)) && !navigationLocked && !(step === "done" && doneBlocked);
}

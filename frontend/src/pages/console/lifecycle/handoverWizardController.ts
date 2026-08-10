import { useReducer } from "react";

import type { MessageKey } from "../../../i18n/messages";
import type { HandoverAction } from "../../../lib/domain";

export type HandoverWizardStepId = "apps" | "grants" | "allocate" | "execute";

export interface HandoverWizardStep {
  id: HandoverWizardStepId;
  labelKey: MessageKey;
}

export const HANDOVER_WIZARD_STEPS: HandoverWizardStep[] = [
  { id: "apps", labelKey: "handover.wizard.step.apps" },
  { id: "grants", labelKey: "handover.wizard.step.grants" },
  { id: "allocate", labelKey: "handover.wizard.step.allocate" },
  { id: "execute", labelKey: "handover.wizard.step.execute" },
];

export interface HandoverWizardControllerState {
  step: HandoverWizardStepId;
}

export type HandoverWizardControllerEvent =
  | { type: "go"; step: HandoverWizardStepId }
  | { type: "next" }
  | { type: "back" };

const STEP_INDEX = new Map(HANDOVER_WIZARD_STEPS.map((step, index) => [step.id, index] as const));

export function handoverWizardReducer(
  state: HandoverWizardControllerState,
  event: HandoverWizardControllerEvent,
): HandoverWizardControllerState {
  const index = stepIndex(state.step);
  if (event.type === "go") {
    return { step: event.step };
  }
  if (event.type === "back") {
    return { step: HANDOVER_WIZARD_STEPS[Math.max(index - 1, 0)].id };
  }
  return { step: HANDOVER_WIZARD_STEPS[Math.min(index + 1, HANDOVER_WIZARD_STEPS.length - 1)].id };
}

export function stepIndex(step: HandoverWizardStepId): number {
  const index = STEP_INDEX.get(step);
  if (index === undefined) {
    throw new Error(`未知交接向导步骤: ${step}`);
  }
  return index;
}

export function isFirstStep(step: HandoverWizardStepId): boolean {
  return stepIndex(step) === 0;
}

export function isLastStep(step: HandoverWizardStepId): boolean {
  return stepIndex(step) === HANDOVER_WIZARD_STEPS.length - 1;
}

/** blocked 应用不可进入后续段。 */
export function canSelectActionForWizard(action: HandoverAction): boolean {
  return action.status !== "blocked";
}

export function useHandoverWizardController() {
  const [state, dispatch] = useReducer(handoverWizardReducer, { step: "apps" });
  return {
    step: state.step,
    stepIndex: stepIndex(state.step),
    isFirstStep: isFirstStep(state.step),
    isLastStep: isLastStep(state.step),
    goTo: (step: HandoverWizardStepId) => dispatch({ type: "go", step }),
    goNext: () => dispatch({ type: "next" }),
    goBack: () => dispatch({ type: "back" }),
  };
}

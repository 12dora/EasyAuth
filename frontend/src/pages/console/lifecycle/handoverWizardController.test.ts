import { describe, expect, test } from "vitest";

import {
  handoverWizardReducer,
  isFirstStep,
  isLastStep,
  stepIndex,
  type HandoverWizardControllerState,
} from "./handoverWizardController";

describe("handoverWizardReducer", () => {
  test("按判别事件前进且停在最后一步", () => {
    let state: HandoverWizardControllerState = { step: "apps" };
    state = handoverWizardReducer(state, { type: "next" });
    expect(state.step).toBe("receivers");
    state = handoverWizardReducer(state, { type: "next" });
    state = handoverWizardReducer(state, { type: "next" });
    state = handoverWizardReducer(state, { type: "next" });
    state = handoverWizardReducer(state, { type: "next" });
    expect(state.step).toBe("execute");
  });

  test("后退停在第一步", () => {
    let state: HandoverWizardControllerState = { step: "apps" };
    state = handoverWizardReducer(state, { type: "back" });
    expect(state.step).toBe("apps");
  });

  test("可以直接跳转到指定步骤", () => {
    const state = handoverWizardReducer({ step: "apps" }, { type: "go", step: "preview" });
    expect(state.step).toBe("preview");
    expect(stepIndex(state.step)).toBe(3);
    expect(isFirstStep("apps")).toBe(true);
    expect(isLastStep("execute")).toBe(true);
  });
});

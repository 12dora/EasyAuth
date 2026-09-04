import { describe, expect, test } from "vitest";

import type { HandoverAction } from "../../../lib/domain";
import {
  canSelectActionForWizard,
  handoverWizardReducer,
  isFirstStep,
  isLastStep,
  stepIndex,
  type HandoverWizardControllerState,
} from "./handoverWizardController";

describe("handoverWizardReducer", () => {
  test("四段前进且停在最后一步", () => {
    let state: HandoverWizardControllerState = { step: "apps" };
    state = handoverWizardReducer(state, { type: "next" });
    expect(state.step).toBe("grants");
    state = handoverWizardReducer(state, { type: "next" });
    expect(state.step).toBe("allocate");
    state = handoverWizardReducer(state, { type: "next" });
    expect(state.step).toBe("execute");
    state = handoverWizardReducer(state, { type: "next" });
    expect(state.step).toBe("execute");
  });

  test("后退停在第一步", () => {
    let state: HandoverWizardControllerState = { step: "apps" };
    state = handoverWizardReducer(state, { type: "back" });
    expect(state.step).toBe("apps");
  });

  test("可以直接跳转到指定步骤", () => {
    const state = handoverWizardReducer({ step: "apps" }, { type: "go", step: "allocate" });
    expect(state.step).toBe("allocate");
    expect(stepIndex(state.step)).toBe(2);
    expect(isFirstStep("apps")).toBe(true);
    expect(isLastStep("execute")).toBe(true);
  });

  test("blocked 应用不可进入后续段", () => {
    const blocked: HandoverAction = {
      app_key: "x",
      app_name: "X",
      app_alias: "",
      status: "blocked",
      blocked_reason: "capability_undeclared",
      skip_reason: "",
      skipped_by: "",
      skipped_at: null,
      skip_history: [],
      last_error: "",
      allowed_actions: [],
      confirm_version: 0,
      overrides_version: 0,
      batch_progress: null,
      asset_types: [],
      approval_instance_warning: null,
      grant_receiver: null,
      summary: null,
      data_completed_at: null,
    };
    expect(canSelectActionForWizard(blocked)).toBe(false);
    expect(canSelectActionForWizard({ ...blocked, status: "pending" })).toBe(true);
  });
});

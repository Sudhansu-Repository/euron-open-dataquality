import { describe, expect, it } from "vitest";

import {
  CHECK_TYPES,
  checkTypeLabel,
  dimensionLabel,
  incidentStatusLabel,
  incidentStatusTone,
  notificationTone,
  resultLabel,
  resultTone,
  RULE_KINDS,
  ruleKindLabel,
  scanStatusTone,
  scoreLabel,
  scoreTone,
  severityLabel,
  severityTone,
} from "@/lib/quality";

describe("check results", () => {
  it("colors a failure by its severity", () => {
    expect(resultTone("pass", "error")).toBe("success");
    expect(resultTone("fail", "error")).toBe("danger");
    expect(resultTone("fail", "warn")).toBe("warning");
    expect(resultTone("error", "error")).toBe("neutral");
  });
  it("names each outcome in words", () => {
    expect(resultLabel("pass", "warn")).toBe("Passed");
    expect(resultLabel("fail", "error")).toBe("Failed");
    expect(resultLabel("fail", "warn")).toBe("Warning");
    expect(resultLabel("error", "error")).toBe("Could not run");
  });
});

describe("scores", () => {
  it("draws the line at 98 and 90", () => {
    expect(scoreTone(100)).toBe("success");
    expect(scoreTone(98)).toBe("success");
    expect(scoreTone(97.9)).toBe("warning");
    expect(scoreTone(90)).toBe("warning");
    expect(scoreTone(89.9)).toBe("danger");
    expect(scoreTone(null)).toBe("neutral");
    expect(scoreLabel(99)).toBe("Healthy");
    expect(scoreLabel(92)).toBe("Needs attention");
    expect(scoreLabel(50)).toBe("Poor");
    expect(scoreLabel(undefined)).toBe("Not scanned");
  });
});

describe("labels", () => {
  it("labels check types and dimensions, falling back to the raw value", () => {
    expect(checkTypeLabel("not_null")).toBe("Not null");
    expect(checkTypeLabel("mystery")).toBe("mystery");
    expect(dimensionLabel("completeness")).toBe("Completeness");
    for (const t of Object.values(CHECK_TYPES)) expect(t.description).toMatch(/\.$/);
  });
  it("labels scan statuses with a tone", () => {
    expect(scanStatusTone("succeeded")).toBe("success");
    expect(scanStatusTone("failed")).toBe("danger");
    expect(scanStatusTone("running")).toBe("info");
    expect(scanStatusTone("unknown")).toBe("neutral");
  });
  it("labels alert rule kinds", () => {
    expect(ruleKindLabel("check_failed")).toBe("A check fails");
    expect(ruleKindLabel("anomaly")).toBe("Unusual change");
    expect(ruleKindLabel("new_kind")).toBe("new_kind");
    expect(ruleKindLabel(null)).toBe("Rule");
    expect(Object.keys(RULE_KINDS)).toEqual(["check_failed", "score_below", "anomaly", "schema_change", "scan_failed"]);
  });
  it("tones incidents and notifications", () => {
    expect(severityTone("error")).toBe("danger");
    expect(severityTone("warn")).toBe("warning");
    expect(severityTone("info")).toBe("info");
    expect(severityLabel("warn")).toBe("Warning");
    expect(incidentStatusTone("open")).toBe("danger");
    expect(incidentStatusTone("acknowledged")).toBe("warning");
    expect(incidentStatusTone("resolved")).toBe("success");
    expect(incidentStatusLabel("acknowledged")).toBe("Acknowledged");
    expect(notificationTone("failed")).toBe("danger");
    expect(notificationTone("sent")).toBe("success");
    expect(notificationTone("pending")).toBe("neutral");
  });
});

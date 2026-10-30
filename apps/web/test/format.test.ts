import { describe, expect, it } from "vitest";

import { formatBytes, formatCompact, formatDateTime, formatDuration, formatNumber, formatPercent, formatRatio, formatRelative, initials } from "@/lib/format";

describe("numbers", () => {
  it("groups thousands and handles missing values", () => {
    expect(formatNumber(14923)).toBe("14,923");
    expect(formatNumber(null)).toBe("n/a");
    expect(formatNumber(Number.NaN)).toBe("n/a");
  });
  it("shows ratios and percentages with one decimal, dropping .0", () => {
    expect(formatRatio(0.2462)).toBe("24.6%");
    expect(formatRatio(1)).toBe("100%");
    expect(formatPercent(60)).toBe("60%");
    expect(formatRatio(undefined)).toBe("n/a");
  });
  it("sizes bytes in B, KB and MB", () => {
    expect(formatBytes(812)).toBe("812 B");
    expect(formatBytes(4300)).toBe("4.2 KB");
    expect(formatBytes(12 * 1024 * 1024)).toBe("12 MB");
  });
});

describe("dates", () => {
  const now = new Date("2026-10-28T12:00:00Z");
  it("says how long ago, then falls back to a date", () => {
    expect(formatRelative("2026-10-28T11:59:40Z", now)).toBe("just now");
    expect(formatRelative("2026-10-28T11:55:00Z", now)).toBe("5m ago");
    expect(formatRelative("2026-10-28T09:00:00Z", now)).toBe("3h ago");
    expect(formatRelative("2026-10-26T12:00:00Z", now)).toBe("2d ago");
    expect(formatRelative("2026-09-01T12:00:00Z", now)).toMatch(/Sep 1, 2026/);
    expect(formatRelative(null, now)).toBe("Never");
  });
  it("never throws on bad input", () => {
    expect(formatDateTime("not a date")).toBe("n/a");
    expect(formatDateTime(undefined)).toBe("n/a");
  });
  it("builds avatar initials", () => {
    expect(initials("Avery Chen")).toBe("AC");
    expect(initials("Mei")).toBe("M");
    expect(initials("")).toBe("?");
  });
});

describe("compact numbers and durations", () => {
  it("abbreviates large counts", () => {
    expect(formatCompact(950)).toBe("950");
    expect(formatCompact(1200)).toBe("1.2K");
    expect(formatCompact(3_400_000)).toBe("3.4M");
    expect(formatCompact(null)).toBe("n/a");
  });
  it("formats durations from milliseconds", () => {
    expect(formatDuration(840)).toBe("840 ms");
    expect(formatDuration(2400)).toBe("2.4 s");
    expect(formatDuration(3000)).toBe("3 s");
    expect(formatDuration(190_000)).toBe("3m 10s");
    expect(formatDuration(undefined)).toBe("n/a");
  });
});

describe("plural", () => {
  it("puts the noun in the right number", async () => {
    const { plural } = await import("@/lib/format");
    expect(plural(1, "row")).toBe("1 row");
    expect(plural(2000, "row")).toBe("2,000 rows");
    expect(plural(0, "check")).toBe("0 checks");
  });
});

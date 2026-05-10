/**
 * Adversarial extra tests for synthetic-lmp.ts — covers gaps in synthetic-lmp.test.ts.
 */
import { describe, it, expect } from "vitest";
import {
  generateDayLmp,
  iterateDates,
} from "../src/synthetic-lmp.js";

describe("generateDayLmp — custom base price", () => {
  it("higher base price produces higher average LMP than default", () => {
    const date = new Date("2024-03-11T00:00:00Z"); // Monday
    const defaultPoints = generateDayLmp(date, 35);
    const highPoints = generateDayLmp(date, 70);
    const defaultMean = defaultPoints.reduce((s, p) => s + p.lmp, 0) / 24;
    const highMean = highPoints.reduce((s, p) => s + p.lmp, 0) / 24;
    expect(highMean).toBeGreaterThan(defaultMean);
  });

  it("base price delta shifts every price by approximately the delta", () => {
    const date = new Date("2024-03-11T00:00:00Z"); // Monday — no weekend discount
    const base35 = generateDayLmp(date, 35);
    const base50 = generateDayLmp(date, 50);
    // Same RNG seed → same noise and spike outcomes; delta should be consistent
    for (let h = 0; h < 24; h++) {
      const p35 = base35[h]!;
      const p50 = base50[h]!;
      // If no spike occurred at this hour, difference should be exactly 15
      // Spikes can vary the absolute values so we allow a generous tolerance,
      // but without a spike both should shift by exactly the base delta
      if (p35.lmp < 100 && p50.lmp < 100) {
        expect(p50.lmp - p35.lmp).toBeCloseTo(15, 5);
      }
    }
  });

  it("base price of 0 still produces non-negative prices (clamped to 0.01)", () => {
    const date = new Date("2024-01-15T00:00:00Z");
    const points = generateDayLmp(date, 0);
    for (const p of points) {
      expect(p.lmp).toBeGreaterThanOrEqual(0.01);
    }
  });
});

describe("generateDayLmp — price spike behavior", () => {
  it("can produce prices above 100 (spike territory) across a large sample of dates", () => {
    // Scan many dates; 1% per hour * 24 hours = ~22% chance per day of at least one spike
    // Over 50 days we expect spikes with extremely high probability
    let foundSpike = false;
    for (let d = 1; d <= 50 && !foundSpike; d++) {
      const date = new Date(`2024-01-${String(d % 28 + 1).padStart(2, "0")}T00:00:00Z`);
      const points = generateDayLmp(date, 35);
      if (points.some((p) => p.lmp > 100)) {
        foundSpike = true;
      }
    }
    expect(foundSpike).toBe(true);
  });

  it("spike prices can exceed 100 $/MWh (verify spike range 100–500+)", () => {
    // Use the known spike structure: spike = rng() * 400 + 100 when rng() < 0.01
    // The maximum possible spike value is 400 + 100 = 500 added to base
    // Scan dates until we find a price > 100 to confirm spike amplitude
    let maxLmp = 0;
    for (let d = 1; d <= 100; d++) {
      const date = new Date(`2024-01-${String((d % 28) + 1).padStart(2, "0")}T00:00:00Z`);
      const points = generateDayLmp(date, 35);
      for (const p of points) {
        if (p.lmp > maxLmp) maxLmp = p.lmp;
      }
    }
    // We sampled 2400 price intervals; 1% chance per interval → expect ~24 spikes
    // The minimum spike value when triggered is base + shape + noise + 100 > 100
    expect(maxLmp).toBeGreaterThan(100);
  });
});

describe("iterateDates — boundary crossings", () => {
  it("crosses month boundary (Jan 31 → Feb 1)", () => {
    const dates = iterateDates("2024-01-31", "2024-02-01");
    expect(dates).toHaveLength(2);
    expect(dates[0]?.toISOString().slice(0, 10)).toBe("2024-01-31");
    expect(dates[1]?.toISOString().slice(0, 10)).toBe("2024-02-01");
  });

  it("crosses year boundary (Dec 31 → Jan 1)", () => {
    const dates = iterateDates("2024-12-31", "2025-01-01");
    expect(dates).toHaveLength(2);
    expect(dates[0]?.toISOString().slice(0, 10)).toBe("2024-12-31");
    expect(dates[1]?.toISOString().slice(0, 10)).toBe("2025-01-01");
  });

  it("crosses Feb 28 to Feb 29 in a leap year (2024)", () => {
    const dates = iterateDates("2024-02-28", "2024-03-01");
    expect(dates).toHaveLength(3); // Feb 28, Feb 29, Mar 1
    expect(dates[1]?.toISOString().slice(0, 10)).toBe("2024-02-29");
  });

  it("Feb 28 to Mar 1 in a non-leap year has only 2 days (no Feb 29)", () => {
    const dates = iterateDates("2023-02-28", "2023-03-01");
    expect(dates).toHaveLength(2);
    expect(dates[0]?.toISOString().slice(0, 10)).toBe("2023-02-28");
    expect(dates[1]?.toISOString().slice(0, 10)).toBe("2023-03-01");
  });

  it("spans a full month correctly (Jan 2024 = 31 days)", () => {
    const dates = iterateDates("2024-01-01", "2024-01-31");
    expect(dates).toHaveLength(31);
  });

  it("all dates in range have consistent UTC midnight time", () => {
    const dates = iterateDates("2024-01-28", "2024-02-02");
    for (const d of dates) {
      expect(d.getUTCHours()).toBe(0);
      expect(d.getUTCMinutes()).toBe(0);
      expect(d.getUTCSeconds()).toBe(0);
      expect(d.getUTCMilliseconds()).toBe(0);
    }
  });

  it("startDate > endDate returns empty array", () => {
    expect(iterateDates("2024-02-01", "2024-01-01")).toHaveLength(0);
  });
});

/**
 * Adversarial extra tests for SocTracker — covers gaps in state.test.ts.
 */
import { describe, it, expect } from "vitest";
import { SocTracker } from "../src/state.js";
import type { BatteryConfig } from "../src/config.js";

const cfg: BatteryConfig = {
  capacityMwh: 100,
  maxChargeMw: 25,
  maxDischargeMw: 25,
  etaCharge: 0.92,
  etaDischarge: 0.92,
  socMinPct: 0.10,
  socMaxPct: 0.90,
  initialSocPct: 0.50,
  degradationPerMwh: 2.0,
};

describe("SocTracker — simultaneous charge and discharge", () => {
  it("applying both charge and discharge in the same interval applies both effects", () => {
    const t = new SocTracker(cfg);
    // charge 10 MW and discharge 10 MW simultaneously
    t.apply(10, 10);
    // gained = 10 * 0.92 = 9.2, lost = 10 → net = 50 + 9.2 - 10 = 49.2
    expect(t.socMwh).toBeCloseTo(50 + 10 * 0.92 - 10);
  });

  it("cycles accumulate from both charge and discharge in same call", () => {
    const t = new SocTracker(cfg);
    t.apply(10, 10);
    // (10 + 10) / (2 * 100) = 0.1
    expect(t.cycles).toBeCloseTo((10 + 10) / (2 * 100));
  });

  it("equal charge and discharge may still move SoC due to etaCharge < 1", () => {
    const t = new SocTracker(cfg);
    const before = t.socMwh;
    // charge 25 MW with etaCharge 0.92 and discharge 25 MW
    // gained = 25 * 0.92 = 23, lost = 25 → net = -2 → SoC decreases
    t.apply(25, 25);
    // net effect should be negative (etaCharge loss)
    expect(t.socMwh).toBeLessThan(before);
  });
});

describe("SocTracker — applySchedule edge cases", () => {
  it("empty array leaves SoC unchanged", () => {
    const t = new SocTracker(cfg);
    const before = t.socMwh;
    t.applySchedule([]);
    expect(t.socMwh).toBe(before);
  });

  it("empty array leaves cycles unchanged", () => {
    const t = new SocTracker(cfg);
    t.applySchedule([]);
    expect(t.cycles).toBe(0);
  });

  it("single-interval schedule applies exactly that interval", () => {
    const t = new SocTracker(cfg);
    t.applySchedule([
      { timestamp: "t1", charge_mw: 0, discharge_mw: 20, market: "DA_ENERGY", expected_revenue_dollars: 0 },
    ]);
    expect(t.socMwh).toBeCloseTo(50 - 20);
  });
});

describe("SocTracker — cycles accumulate across multiple apply calls", () => {
  it("two successive charge calls accumulate cycles additively", () => {
    const t = new SocTracker(cfg);
    t.apply(10, 0); // 10 / 200 = 0.05
    t.apply(10, 0); // another 0.05
    expect(t.cycles).toBeCloseTo(0.10);
  });

  it("charge then discharge sums both in cycle count", () => {
    const t = new SocTracker(cfg);
    t.apply(25, 0); // 25 / 200 = 0.125
    t.apply(0, 25); // 25 / 200 = 0.125
    expect(t.cycles).toBeCloseTo(0.25);
  });

  it("many small charges sum correctly", () => {
    const t = new SocTracker(cfg);
    for (let i = 0; i < 8; i++) {
      t.apply(2, 0); // each 2/200 = 0.01
    }
    expect(t.cycles).toBeCloseTo(0.08);
  });

  it("reset zeroes cycles even after accumulation", () => {
    const t = new SocTracker(cfg);
    t.apply(10, 0);
    t.apply(0, 10);
    expect(t.cycles).toBeGreaterThan(0);
    t.reset();
    expect(t.cycles).toBe(0);
  });
});

describe("SocTracker — negative dischargeMw treated as zero", () => {
  it("negative dischargeMw does not reduce SoC", () => {
    const t = new SocTracker(cfg);
    const before = t.socMwh;
    t.apply(0, -5);
    expect(t.socMwh).toBeCloseTo(before);
  });

  it("negative dischargeMw does not add to cycles", () => {
    const t = new SocTracker(cfg);
    t.apply(0, -5);
    expect(t.cycles).toBe(0);
  });
});

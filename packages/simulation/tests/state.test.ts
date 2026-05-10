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

describe("SocTracker", () => {
  it("initializes to initialSocPct", () => {
    const t = new SocTracker(cfg);
    expect(t.socPct).toBeCloseTo(0.50);
    expect(t.socMwh).toBeCloseTo(50);
  });

  it("charge increases SoC by chargeMw * etaCharge", () => {
    const t = new SocTracker(cfg);
    t.apply(10, 0);
    expect(t.socMwh).toBeCloseTo(50 + 10 * 0.92);
  });

  it("discharge decreases SoC by dischargeMw", () => {
    const t = new SocTracker(cfg);
    t.apply(0, 10);
    expect(t.socMwh).toBeCloseTo(50 - 10);
  });

  it("SoC is clamped to socMaxPct when over-charging", () => {
    const t = new SocTracker(cfg);
    t.apply(1000, 0); // would push SoC way above max
    expect(t.socPct).toBeCloseTo(0.90);
  });

  it("SoC is clamped to socMinPct when over-discharging", () => {
    const t = new SocTracker(cfg);
    t.apply(0, 1000); // would push SoC way below min
    expect(t.socPct).toBeCloseTo(0.10);
  });

  it("cycles increase with charge and discharge", () => {
    const t = new SocTracker(cfg);
    t.apply(25, 0); // 25 MWh charge in 100 MWh battery = 0.125 half-cycles
    expect(t.cycles).toBeCloseTo(25 / (2 * 100));
  });

  it("reset restores initial state", () => {
    const t = new SocTracker(cfg);
    t.apply(25, 0);
    t.reset();
    expect(t.socPct).toBeCloseTo(0.50);
    expect(t.cycles).toBe(0);
  });

  it("applySchedule applies all intervals in order", () => {
    const t = new SocTracker(cfg);
    t.applySchedule([
      { timestamp: "t1", charge_mw: 10, discharge_mw: 0, market: "DA_ENERGY", expected_revenue_dollars: 0 },
      { timestamp: "t2", charge_mw: 0, discharge_mw: 5, market: "DA_ENERGY", expected_revenue_dollars: 0 },
    ]);
    // +10*0.92 - 5 = +4.2 net MWh → 50 + 4.2 = 54.2
    expect(t.socMwh).toBeCloseTo(50 + 10 * 0.92 - 5);
  });

  it("negative charge_mw is treated as zero", () => {
    const t = new SocTracker(cfg);
    t.apply(-5, 0);
    expect(t.socMwh).toBeCloseTo(50); // no change
  });
});

import type { BatteryConfig } from "./config.js";

export interface DispatchInterval {
  timestamp: string;
  charge_mw: number;
  discharge_mw: number;
  market: string;
  expected_revenue_dollars: number;
}

export class SocTracker {
  private socMwhInternal: number;
  private cyclesInternal = 0;

  constructor(private readonly cfg: BatteryConfig) {
    this.socMwhInternal = cfg.initialSocPct * cfg.capacityMwh;
  }

  apply(chargeMw: number, dischargeMw: number): void {
    const gained = Math.max(0, chargeMw) * this.cfg.etaCharge;
    const lost = Math.max(0, dischargeMw);
    const raw = this.socMwhInternal + gained - lost;
    this.socMwhInternal = Math.min(
      this.cfg.socMaxPct * this.cfg.capacityMwh,
      Math.max(this.cfg.socMinPct * this.cfg.capacityMwh, raw)
    );
    // half-cycle = one full charge or discharge event
    this.cyclesInternal += (Math.max(0, chargeMw) + Math.max(0, dischargeMw)) / (2 * this.cfg.capacityMwh);
  }

  applySchedule(intervals: DispatchInterval[]): void {
    for (const iv of intervals) {
      this.apply(iv.charge_mw, iv.discharge_mw);
    }
  }

  get socMwh(): number {
    return this.socMwhInternal;
  }

  get socPct(): number {
    return this.socMwhInternal / this.cfg.capacityMwh;
  }

  get cycles(): number {
    return this.cyclesInternal;
  }

  reset(): void {
    this.socMwhInternal = this.cfg.initialSocPct * this.cfg.capacityMwh;
    this.cyclesInternal = 0;
  }
}

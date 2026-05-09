import type { ISO, Market } from "./messages.js";

export interface LMPRecord {
  timestamp: string;
  iso: ISO;
  node: string;
  lmp: number;
  energyComponent: number;
  congestionComponent: number;
  lossComponent: number;
}

export interface AncillaryPriceRecord {
  timestamp: string;
  iso: ISO;
  service: Market;
  clearingPrice: number;
  mileage?: number;
}

export interface PriceForecast {
  iso: ISO;
  node: string;
  market: Market;
  generatedAt: string;
  horizon: { start: string; end: string };
  intervals: ForecastInterval[];
  modelId: string;
  confidence: number;
}

export interface ForecastInterval {
  timestamp: string;
  mean: number;
  p10: number;
  p90: number;
}

export interface BatteryState {
  assetId: string;
  timestamp: string;
  socPct: number;
  socMwh: number;
  availableChargeMw: number;
  availableDischargeMw: number;
  tempC: number;
  cycleCount: number;
  degradationCostPerCycleDollars: number;
}

export interface DispatchInterval {
  timestamp: string;
  chargeMw: number;
  dischargeMw: number;
  market: Market;
  expectedRevenueDollars: number;
}

export interface DispatchSchedule {
  assetId: string;
  generatedAt: string;
  horizon: { start: string; end: string };
  intervals: DispatchInterval[];
  totalExpectedRevenueDollars: number;
  solverStatus: "optimal" | "infeasible" | "timeout";
}

export interface Bid {
  assetId: string;
  iso: ISO;
  market: Market;
  intervalStart: string;
  intervalEnd: string;
  quantityMw: number;
  priceDollarsPerMwh: number;
}

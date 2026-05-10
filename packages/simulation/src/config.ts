export interface BatteryConfig {
  capacityMwh: number;
  maxChargeMw: number;
  maxDischargeMw: number;
  etaCharge: number;
  etaDischarge: number;
  socMinPct: number;
  socMaxPct: number;
  initialSocPct: number;
  degradationPerMwh: number;
}

export interface SimConfig {
  assetId: string;
  iso: string;
  node: string;
  markets: string[];
  startDate: string;
  endDate: string;
  battery: BatteryConfig;
  forecastingUrl: string;
  optimizationUrl: string;
}

export const DEFAULT_BATTERY: BatteryConfig = {
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

export const DEFAULT_SIM_CONFIG: SimConfig = {
  assetId: "BESS-001",
  iso: "ERCOT",
  node: "HB_NORTH",
  markets: ["DA_ENERGY"],
  startDate: "2024-01-01",
  endDate: "2024-01-07",
  battery: DEFAULT_BATTERY,
  forecastingUrl:
    process.env["FORECASTING_SERVICE_URL"] ?? "http://localhost:8001",
  optimizationUrl:
    process.env["OPTIMIZATION_SERVICE_URL"] ?? "http://localhost:8002",
};

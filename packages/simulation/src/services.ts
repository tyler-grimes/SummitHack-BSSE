import type { LmpPoint } from "./synthetic-lmp.js";

export interface ForecastInterval {
  timestamp: string;
  mean: number;
  p10: number;
  p90: number;
}

export interface ForecastResult {
  iso: string;
  node: string;
  market: string;
  intervals: ForecastInterval[];
  model_id: string;
  confidence: number;
}

export interface OptimizeResult {
  asset_id: string;
  intervals: Array<{
    timestamp: string;
    charge_mw: number;
    discharge_mw: number;
    market: string;
    expected_revenue_dollars: number;
  }>;
  total_expected_revenue_dollars: number;
  solver_status: string;
}

export async function callForecast(
  url: string,
  iso: string,
  node: string,
  market: string,
  horizonHours: number,
  asOfDate?: string
): Promise<ForecastResult[]> {
  const resp = await fetch(`${url}/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      iso,
      nodes: [node],
      market,
      horizon_hours: horizonHours,
      as_of_date: asOfDate ?? null,
    }),
  });
  if (!resp.ok) {
    throw new Error(`Forecasting service ${resp.status}: ${await resp.text()}`);
  }
  return (await resp.json()) as ForecastResult[];
}

export async function callOptimize(
  url: string,
  assetId: string,
  forecastsByMarket: Record<string, ForecastInterval[]>,
  horizonHours: number,
  markets: string[],
  currentSocPct?: number
): Promise<OptimizeResult> {
  const resp = await fetch(`${url}/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      asset_id: assetId,
      forecasts: forecastsByMarket,
      horizon_hours: horizonHours,
      markets,
      current_soc_pct: currentSocPct ?? null,
    }),
  });
  if (!resp.ok) {
    throw new Error(`Optimization service ${resp.status}: ${await resp.text()}`);
  }
  return (await resp.json()) as OptimizeResult;
}

export function lmpToForecastIntervals(points: LmpPoint[]): ForecastInterval[] {
  return points.map((p) => ({
    timestamp: p.timestamp,
    mean: p.lmp,
    p10: p.lmp * 0.85,
    p90: p.lmp * 1.15,
  }));
}

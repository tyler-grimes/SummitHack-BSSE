import type { SimConfig } from "./config.js";
import { buildPriceMap, iterateDates } from "./synthetic-lmp.js";
import { fetchActualLmp } from "./actual-lmp.js";
import { SocTracker } from "./state.js";
import { computeDayPnl } from "./pnl.js";
import {
  callForecast,
  callOptimize,
  type ForecastInterval,
} from "./services.js";
import type { DispatchInterval } from "./state.js";

export interface DayResult {
  date: string;
  expectedRevenueDollars: number;
  actualRevenueDollars: number;
  solverStatus: string;
  socStartPct: number;
  socEndPct: number;
  cyclesDelta: number;
}

export interface SimResult {
  config: SimConfig;
  days: DayResult[];
  totalExpectedRevenueDollars: number;
  totalActualRevenueDollars: number;
  totalCycles: number;
  daysSimulated: number;
}

/**
 * Restamp any interval array (forecast or dispatch) to hourly slots on the
 * simulated day.  Validates that the array has at most 24 entries so we never
 * silently produce timestamps that roll into the next day.
 */
function restampToDate<T extends { timestamp: string }>(intervals: T[], date: Date): T[] {
  if (intervals.length > 24) {
    throw new RangeError(
      `restampToDate: expected <= 24 intervals, got ${intervals.length}`
    );
  }
  return intervals.map((iv, i) => {
    const ts = new Date(date);
    ts.setUTCHours(i, 0, 0, 0);
    return { ...iv, timestamp: ts.toISOString() };
  });
}

export async function runSimulation(config: SimConfig): Promise<SimResult> {
  const dates = iterateDates(config.startDate, config.endDate);
  const tracker = new SocTracker(config.battery);
  const days: DayResult[] = [];

  for (const date of dates) {
    const dateStr = date.toISOString().slice(0, 10);
    const actualLmp = await fetchActualLmp(date, config.iso, config.node, config.basePriceMwh);
    const priceMap = buildPriceMap(actualLmp);
    const socStart = tracker.socPct;
    const cyclesBefore = tracker.cycles;

    let solverStatus = "ok";
    let expectedRevenue = 0;
    let actualRevenue = 0;

    try {
      // Call the forecasting service (anchored to "now"), then restamp its
      // intervals onto the simulated day. This gives real forecast prices vs
      // real actual prices → accuracy reflects true model error.
      const forecastsByMarket: Record<string, ForecastInterval[]> = {};
      for (const market of config.markets) {
        const results = await callForecast(
          config.forecastingUrl,
          config.iso,
          config.node,
          market,
          24,
          dateStr  // as_of_date: history limited to this day → day-ahead forecast
        );
        const node = results.find((r) => r.node === config.node);
        const raw: ForecastInterval[] = node?.intervals ?? [];
        forecastsByMarket[market] = restampToDate(raw, date);
      }

      const optimizeResult = await callOptimize(
        config.optimizationUrl,
        config.assetId,
        forecastsByMarket,
        24,
        config.markets,
        socStart  // real current SoC → optimizer plans from correct starting state
      );

      solverStatus = optimizeResult.solver_status;

      // Restamp intervals to simulated day so timestamps match priceMap keys
      const intervals = restampToDate(optimizeResult.intervals, date);

      const { expected, actual } = computeDayPnl(intervals, priceMap, config.battery);
      expectedRevenue = expected;
      actualRevenue = actual;

      tracker.applySchedule(intervals);
    } catch (err) {
      solverStatus = `error: ${err instanceof Error ? err.message : String(err)}`;
    }

    days.push({
      date: dateStr,
      expectedRevenueDollars: expectedRevenue,
      actualRevenueDollars: actualRevenue,
      solverStatus,
      socStartPct: socStart,
      socEndPct: tracker.socPct,
      cyclesDelta: tracker.cycles - cyclesBefore,
    });
  }

  return {
    config,
    days,
    totalExpectedRevenueDollars: days.reduce((s, d) => s + d.expectedRevenueDollars, 0),
    totalActualRevenueDollars: days.reduce((s, d) => s + d.actualRevenueDollars, 0),
    totalCycles: tracker.cycles,
    daysSimulated: days.length,
  };
}

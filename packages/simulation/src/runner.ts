import type { SimConfig } from "./config.js";
import {
  generateDayLmp,
  buildPriceMap,
  iterateDates,
} from "./synthetic-lmp.js";
import { SocTracker } from "./state.js";
import { computeDayPnl } from "./pnl.js";
import {
  callForecast,
  callOptimize,
  lmpToForecastIntervals,
  type ForecastInterval,
} from "./services.js";

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

export async function runSimulation(config: SimConfig): Promise<SimResult> {
  const dates = iterateDates(config.startDate, config.endDate);
  const tracker = new SocTracker(config.battery);
  const days: DayResult[] = [];

  for (const date of dates) {
    const dateStr = date.toISOString().slice(0, 10);
    const actualLmp = generateDayLmp(date, 35);
    const priceMap = buildPriceMap(actualLmp);
    const socStart = tracker.socPct;
    const cyclesBefore = tracker.cycles;

    let solverStatus = "ok";
    let expectedRevenue = 0;
    let actualRevenue = 0;

    try {
      const forecastsByMarket: Record<string, ForecastInterval[]> = {};

      for (const market of config.markets) {
        const forecasts = await callForecast(
          config.forecastingUrl,
          config.iso,
          config.node,
          market,
          24
        );
        const nodeForecasts = forecasts.find((f) => f.node === config.node);
        forecastsByMarket[market] = nodeForecasts?.intervals ?? lmpToForecastIntervals(actualLmp);
      }

      const optimizeResult = await callOptimize(
        config.optimizationUrl,
        config.assetId,
        forecastsByMarket,
        24,
        config.markets
      );

      solverStatus = optimizeResult.solver_status;
      const { expected, actual } = computeDayPnl(
        optimizeResult.intervals,
        priceMap,
        config.battery
      );
      expectedRevenue = expected;
      actualRevenue = actual;

      tracker.applySchedule(optimizeResult.intervals);
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

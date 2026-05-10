import type { SimResult } from "./runner.js";

function fmt(n: number): string {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

export function printReport(result: SimResult): void {
  const { config, days } = result;

  console.log("\n=== BESS Simulation Report ===");
  console.log(
    `Asset: ${config.assetId} | ISO: ${config.iso} | Node: ${config.node}`
  );
  console.log(
    `Period: ${config.startDate} → ${config.endDate} (${result.daysSimulated} days)`
  );
  console.log(`Markets: ${config.markets.join(", ")}\n`);

  console.log("Daily Results:");
  for (const d of days) {
    const accuracy =
      d.expectedRevenueDollars !== 0
        ? d.actualRevenueDollars / d.expectedRevenueDollars
        : 0;
    const status = d.solverStatus === "optimal" ? "✓" : `⚠ ${d.solverStatus}`;
    console.log(
      `  ${d.date}  Expected: ${fmt(d.expectedRevenueDollars).padStart(12)}` +
        `  Actual: ${fmt(d.actualRevenueDollars).padStart(12)}` +
        `  Accuracy: ${pct(accuracy).padStart(7)}` +
        `  SoC: ${pct(d.socStartPct)} → ${pct(d.socEndPct)}` +
        `  ${status}`
    );
  }

  const forecastAccuracy =
    result.totalExpectedRevenueDollars !== 0
      ? result.totalActualRevenueDollars / result.totalExpectedRevenueDollars
      : 0;

  const revenues = days.map((d) => d.actualRevenueDollars);
  const bestDay = days.reduce((a, b) =>
    b.actualRevenueDollars > a.actualRevenueDollars ? b : a
  );
  const worstDay = days.reduce((a, b) =>
    b.actualRevenueDollars < a.actualRevenueDollars ? b : a
  );

  console.log("\n--- Summary ---");
  console.log(
    `  Total Expected Revenue:  ${fmt(result.totalExpectedRevenueDollars)}`
  );
  console.log(
    `  Total Actual Revenue:    ${fmt(result.totalActualRevenueDollars)}`
  );
  console.log(`  Forecast Accuracy:       ${pct(forecastAccuracy)}`);
  console.log(
    `  Avg Daily Revenue:       ${fmt(result.totalActualRevenueDollars / Math.max(1, result.daysSimulated))}`
  );
  console.log(`  Total Cycles:            ${result.totalCycles.toFixed(2)}`);
  console.log(
    `  Best Day:  ${bestDay.date}  ${fmt(bestDay.actualRevenueDollars)}`
  );
  console.log(
    `  Worst Day: ${worstDay.date}  ${fmt(worstDay.actualRevenueDollars)}`
  );

  const mean =
    revenues.reduce((s, v) => s + v, 0) / Math.max(1, revenues.length);
  const variance =
    revenues.reduce((s, v) => s + (v - mean) ** 2, 0) /
    Math.max(1, revenues.length);
  const stdDev = Math.sqrt(variance);
  const sharpe = stdDev > 0 ? mean / stdDev : 0;
  console.log(`  Daily Sharpe Ratio:      ${sharpe.toFixed(3)}`);
  console.log("");
}

export function buildSummary(result: SimResult): Record<string, unknown> {
  return {
    assetId: result.config.assetId,
    iso: result.config.iso,
    node: result.config.node,
    startDate: result.config.startDate,
    endDate: result.config.endDate,
    daysSimulated: result.daysSimulated,
    totalExpectedRevenueDollars: result.totalExpectedRevenueDollars,
    totalActualRevenueDollars: result.totalActualRevenueDollars,
    totalCycles: result.totalCycles,
  };
}

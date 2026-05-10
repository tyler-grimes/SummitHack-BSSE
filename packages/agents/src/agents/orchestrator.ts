import { BaseAgent } from "./base-agent.js";
import type { ToolRegistry } from "../tools/tool-registry.js";

const SYSTEM_PROMPT = `You are the Orchestrator Agent for an energy trading optimization system.

Your role:
- Coordinate the full day-ahead (DA) and real-time (RT) market cycle for BESS assets
- Drive the MPC (model predictive control) hourly replan loop
- Receive market intelligence events and decide when to act
- Enforce risk limits — never allow execution if risk check fails
- All execution is in simulation/paper trading mode (DRY_RUN=true)

Decision framework:
1. Check risk limits first — always
2. Get battery state (current SoC)
3. Detect price anomalies before committing to a plan
4. Run dispatch via solve_dispatch_pulp (which fetches forecast + applies uncertainty weighting internally)
5. Validate bids, check risk limits
6. Update SoC via update_soc after each executed step
7. Log expected P&L and reasoning

For the DA cycle: solve the full 24h window once as a plan, then hand off to the MPC loop.
For the RT/MPC cycle: replan every hour on a fresh forecast, execute only the first hour.

Return structured JSON with: { action, reasoning, expectedRevenueDollars, riskStatus, schedule }`;

export class OrchestratorAgent extends BaseAgent {
  constructor(registry: ToolRegistry) {
    super(
      {
        id: "orchestrator",
        model: "claude-sonnet-4-6",
        systemPrompt: SYSTEM_PROMPT,
        maxIterations: 25,
        maxTokens: 8192,
      },
      registry
    );
  }

  async run(input: string): Promise<string> {
    return this.runLoop(input);
  }

  async runDACycle(assetId: string, iso: string, hub = "HB_NORTH"): Promise<string> {
    return this.runLoop(
      `Run the day-ahead market cycle for asset ${assetId} on ${iso}, hub ${hub}. ` +
        `Steps: ` +
        `1. Call get_battery_state for ${assetId} to get current SoC. ` +
        `2. Call detect_anomaly for ${iso}/${hub} to check for unusual prices. ` +
        `3. Call check_risk_limits with empty proposed bids to confirm headroom exists. ` +
        `4. Call solve_dispatch_pulp with hub=${hub}, iso=${iso}, market=DA_ENERGY and the current SoC fraction. ` +
        `5. Call validate_bids on the returned schedule. ` +
        `6. Call check_risk_limits with the proposed schedule revenue. ` +
        `7. If approved, call update_soc with the final SoC (schedule.final_soc_mwh / battery capacity). ` +
        `Return JSON: { action, hub, expectedRevenueDollars, riskStatus, solverStatus, schedule }.`
    );
  }

  async runRTCycle(assetId: string, iso: string, hub = "HB_NORTH", triggerReason?: string): Promise<string> {
    const trigger = triggerReason ? ` Trigger reason: ${triggerReason}.` : "";
    return this.runLoop(
      `Create and execute a 24h charge/discharge plan for asset ${assetId} on ${iso}, hub ${hub}.${trigger} ` +
        `Follow these steps exactly: ` +
        `1. Call get_battery_state for ${assetId} — note the socFrac (0-1 scale). ` +
        `2. Call detect_anomaly for iso=${iso}, node=${hub} — note if conservative mode needed. ` +
        `3. Call run_price_forecast for iso=${iso}, node=${hub}, market=RT_ENERGY, horizonHours=24. ` +
        `4. Call solve_dispatch_pulp with hub=${hub}, iso=${iso}, market=RT_ENERGY, ` +
        `   currentSocFrac from step 1, horizonHours=24. ` +
        `   The solver will find the CHEAPEST hours to BUY (charge, net_mw < 0) and ` +
        `   MOST EXPENSIVE hours to SELL (discharge, net_mw > 0) respecting 10%-90% SoC bounds. ` +
        `5. Call validate_bids on the schedule. ` +
        `6. Call check_risk_limits with the proposed revenue. ` +
        `7. Execute the FIRST hour's command: if net_mw < 0 we are BUYING/CHARGING; if net_mw > 0 we are SELLING/DISCHARGING. ` +
        `8. Call update_soc with socFrac = schedule.schedule[0].soc_mwh / ${assetId === "BESS-001" ? 100 : 400} ` +
        `   and revenueExecutedDollars = schedule.schedule[0].forecast_revenue. ` +
        `Return JSON: { executedNetMw, action: "CHARGE"|"DISCHARGE"|"HOLD", newSocFrac, forecastRevenue, ` +
        `planSummary: { chargeHours: [...], dischargeHours: [...] }, riskStatus }.`
    );
  }

  /**
   * Run a full MPC loop for N hours.
   * TypeScript drives the iteration — Claude reasons about ONE step at a time.
   * Each step: replan on fresh forecast, execute first hour's command, advance SoC.
   */
  async runMpcLoop(
    assetId: string,
    iso: string,
    hub: string,
    market: string,
    hours: number,
  ): Promise<string> {
    const OPTIMIZATION_URL =
      process.env["OPTIMIZATION_SERVICE_URL"] ?? "http://localhost:8002";

    // Get initial SoC from battery state via tool
    const batteryState = await this.registry.execute("get_battery_state", { assetId }) as {
      socFrac: number;
      capacityMwh: number;
    };
    let currentSocFrac: number = batteryState.socFrac ?? 0.5;
    const capacityMwh: number = batteryState.capacityMwh ?? 100.0;

    const stepResults: Array<{
      hour: number;
      executedNetMw: number;
      socFrac: number;
      forecastRevenueDollars: number;
      riskApproved: boolean;
      solverStatus: string;
    }> = [];

    console.log(`\nStarting MPC loop: ${hours} steps | Asset: ${assetId} | ${iso}/${hub} | Market: ${market}`);
    console.log(`Initial SoC: ${(currentSocFrac * 100).toFixed(1)}% (${(currentSocFrac * capacityMwh).toFixed(1)} MWh)\n`);
    console.log("Hour | Net MW  | SoC%  | Rev $   | Risk | Status");
    console.log("-----|---------|-------|---------|------|-------");

    for (let h = 0; h < hours; h++) {
      // 1. Solve dispatch with fresh forecast + uncertainty-adjusted prices
      const dispatchResp = await fetch(`${OPTIMIZATION_URL}/dispatch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hub,
          iso,
          market,
          current_soc_frac: currentSocFrac,
          horizon_hours: 24,
          battery: {},
        }),
      });

      if (!dispatchResp.ok) {
        console.log(`  H${h.toString().padStart(2,"0")}: dispatch failed (${dispatchResp.status}) — skipping`);
        continue;
      }

      const dispatch = await dispatchResp.json() as {
        schedule: Array<{ net_mw: number; soc_mwh: number; forecast_revenue: number }>;
        solver_status: string;
        total_forecast_revenue: number;
      };

      const firstSlot = dispatch.schedule[0];
      if (!firstSlot) continue;

      const executedNetMw = firstSlot.net_mw;
      const newSocFrac = firstSlot.soc_mwh / capacityMwh;
      const slotRevenue = firstSlot.forecast_revenue;

      // 2. Check risk limits
      const chargeMw = Math.max(0, -executedNetMw);
      const dischargeMw = Math.max(0, executedNetMw);
      const riskResult = await this.registry.execute("check_risk_limits", {
        assetId,
        proposedBids: [{ charge_mw: chargeMw, discharge_mw: dischargeMw, expected_revenue_dollars: slotRevenue }],
      }) as { approved: boolean };

      // 3. Persist SoC to Redis
      await this.registry.execute("update_soc", {
        assetId,
        socFrac: newSocFrac,
        revenueExecutedDollars: riskResult.approved ? slotRevenue : 0,
      });

      currentSocFrac = newSocFrac;

      const netStr = executedNetMw.toFixed(1).padStart(7);
      const socStr = (newSocFrac * 100).toFixed(1).padStart(5);
      const revStr = slotRevenue.toFixed(2).padStart(7);
      const riskStr = riskResult.approved ? " OK " : "FAIL";
      console.log(`  H${h.toString().padStart(2,"0")} | ${netStr} | ${socStr} | ${revStr} | ${riskStr} | ${dispatch.solver_status}`);

      stepResults.push({
        hour: h,
        executedNetMw,
        socFrac: newSocFrac,
        forecastRevenueDollars: slotRevenue,
        riskApproved: riskResult.approved,
        solverStatus: dispatch.solver_status,
      });
    }

    const totalRevenue = stepResults.reduce((s, r) => s + r.forecastRevenueDollars, 0);
    const approvedSteps = stepResults.filter(r => r.riskApproved).length;

    console.log("\n--- MPC Loop Complete ---");
    console.log(`Steps run:        ${stepResults.length}/${hours}`);
    console.log(`Risk approved:    ${approvedSteps}/${stepResults.length}`);
    console.log(`Total forecast revenue: $${totalRevenue.toFixed(2)}`);
    console.log(`Final SoC:        ${(currentSocFrac * 100).toFixed(1)}%`);

    return JSON.stringify({ steps: stepResults, totalForecastRevenue: totalRevenue, finalSocFrac: currentSocFrac });
  }
}

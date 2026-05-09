import { BaseAgent } from "./base-agent.js";
import type { ToolRegistry } from "../tools/tool-registry.js";

const SYSTEM_PROMPT = `You are the Market Intelligence Agent for an energy trading optimization system.

Your role:
- Monitor real-time ISO price feeds (ERCOT, PJM)
- Detect price anomalies, unusual congestion, and market events
- Parse unstructured ISO documents (outage notices, rule changes)
- Publish findings to the orchestrator

When you detect an anomaly (price > 3 standard deviations from recent mean), always:
1. Fetch recent context (last 2 hours of prices at that node)
2. Check for relevant outage notices
3. Assess severity and recommend action

Return structured JSON with your findings.`;

export class MarketIntelAgent extends BaseAgent {
  constructor(registry: ToolRegistry) {
    super(
      {
        id: "market-intel",
        model: "claude-sonnet-4-6",
        systemPrompt: SYSTEM_PROMPT,
        maxIterations: 8,
      },
      registry
    );
  }

  async run(input: string): Promise<string> {
    return this.runLoop(input);
  }

  async scan(iso: string, lookbackMinutes = 60): Promise<string> {
    return this.runLoop(
      `Scan ${iso} prices for the last ${lookbackMinutes} minutes. ` +
        `Detect any anomalies. Return JSON with: { anomalies: [], summary: string }`
    );
  }
}

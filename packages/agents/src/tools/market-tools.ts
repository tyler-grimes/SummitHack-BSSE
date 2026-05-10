import type { ToolDefinition } from "./tool-registry.js";
import {
  queryLmpHistory,
  queryAncillaryPrices,
} from "../db/timescale.js";

export const fetchRealtimeLmp: ToolDefinition = {
  name: "fetch_realtime_lmp",
  description:
    "Fetch recent real-time LMP prices for given ISO nodes from TimescaleDB",
  inputSchema: {
    type: "object",
    properties: {
      iso: {
        type: "string",
        enum: ["ERCOT", "PJM", "CAISO", "ISONE", "MISO", "NYISO", "SPP"],
      },
      nodes: { type: "array", items: { type: "string" } },
      lookbackMinutes: { type: "number", default: 60 },
    },
    required: ["iso", "nodes"],
  },
  handler: async (input) => {
    const { iso, nodes, lookbackMinutes = 60 } = input as {
      iso: string;
      nodes: string[];
      lookbackMinutes?: number;
    };

    const records: Array<{ node: string; time: string; lmp: number }> = [];
    for (const node of nodes) {
      const rows = await queryLmpHistory(iso, node, lookbackMinutes);
      for (const row of rows) {
        records.push({ node, time: row.time.toISOString(), lmp: row.lmp });
      }
    }
    records.sort((a, b) => a.time.localeCompare(b.time));

    return { iso, nodes, lookbackMinutes, records };
  },
};

export const fetchAncillaryPrices: ToolDefinition = {
  name: "fetch_ancillary_prices",
  description:
    "Fetch ancillary service clearing prices (regulation, spinning reserves, etc.)",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string" },
      services: {
        type: "array",
        items: {
          type: "string",
          enum: ["REG_UP", "REG_DOWN", "SPIN", "NONSPIN"],
        },
      },
      lookbackMinutes: { type: "number", default: 60 },
    },
    required: ["iso", "services"],
  },
  handler: async (input) => {
    const { iso, services, lookbackMinutes = 60 } = input as {
      iso: string;
      services: string[];
      lookbackMinutes?: number;
    };

    const rows = await queryAncillaryPrices(iso, services, lookbackMinutes);
    const records = rows.map((r) => ({
      time: r.time.toISOString(),
      service: r.service,
      price_mw: r.price_mw,
      total_mw: r.total_mw,
    }));

    return { iso, services, lookbackMinutes, records };
  },
};

export const detectAnomaly: ToolDefinition = {
  name: "detect_anomaly",
  description:
    "Detect statistical anomalies in price time series (z-score based)",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string" },
      node: { type: "string" },
      lookbackHours: { type: "number", default: 24 },
      sigmaThreshold: { type: "number", default: 3.0 },
    },
    required: ["iso", "node"],
  },
  handler: async (input) => {
    const {
      iso,
      node,
      lookbackHours = 24,
      sigmaThreshold = 3.0,
    } = input as {
      iso: string;
      node: string;
      lookbackHours?: number;
      sigmaThreshold?: number;
    };

    const rows = await queryLmpHistory(iso, node, lookbackHours * 60);
    if (rows.length < 2) {
      return {
        isAnomaly: false,
        sigma: 0,
        currentPrice: null,
        historicalMean: null,
        historicalStd: null,
        dataPoints: rows.length,
        message: "Insufficient data for anomaly detection",
      };
    }

    const prices = rows.map((r) => r.lmp);
    const current = prices[prices.length - 1] as number;
    const history = prices.slice(0, -1);
    const mean = history.reduce((s, v) => s + v, 0) / history.length;
    const variance =
      history.reduce((s, v) => s + (v - mean) ** 2, 0) / history.length;
    const std = Math.sqrt(variance);
    const sigma = std > 0 ? (current - mean) / std : 0;

    return {
      isAnomaly: Math.abs(sigma) > sigmaThreshold,
      sigma,
      currentPrice: current,
      historicalMean: mean,
      historicalStd: std,
      sigmaThreshold,
      dataPoints: rows.length,
    };
  },
};

export const parseIsoDocument: ToolDefinition = {
  name: "parse_iso_document",
  description:
    "Parse unstructured ISO documents (outage notices, rule changes, settlement PDFs)",
  inputSchema: {
    type: "object",
    properties: {
      source: { type: "string", description: "URL or file path" },
      docType: {
        type: "string",
        enum: ["outage_notice", "rule_change", "settlement"],
      },
    },
    required: ["source", "docType"],
  },
  handler: (_input) => {
    return Promise.resolve({
      parsed: {},
      rawText: "",
      status: "not_implemented",
      message: "ISO document parsing not available in simulation mode",
    });
  },
};

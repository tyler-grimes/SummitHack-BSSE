import type { ToolDefinition } from "./tool-registry.js";

export const fetchRealtimeLmp: ToolDefinition = {
  name: "fetch_realtime_lmp",
  description: "Fetch recent real-time LMP prices for given ISO nodes from TimescaleDB",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string", enum: ["ERCOT", "PJM", "CAISO", "ISONE", "MISO", "NYISO", "SPP"] },
      nodes: { type: "array", items: { type: "string" } },
      lookbackMinutes: { type: "number", default: 60 },
    },
    required: ["iso", "nodes"],
  },
  handler: async (input) => {
    // TODO: query TimescaleDB
    const { iso, nodes, lookbackMinutes = 60 } = input as {
      iso: string;
      nodes: string[];
      lookbackMinutes?: number;
    };
    return { iso, nodes, lookbackMinutes, records: [], status: "stub" };
  },
};

export const fetchAncillaryPrices: ToolDefinition = {
  name: "fetch_ancillary_prices",
  description: "Fetch ancillary service clearing prices (regulation, spinning reserves, etc.)",
  inputSchema: {
    type: "object",
    properties: {
      iso: { type: "string" },
      services: {
        type: "array",
        items: { type: "string", enum: ["REG_UP", "REG_DOWN", "SPIN", "NONSPIN"] },
      },
      lookbackMinutes: { type: "number", default: 60 },
    },
    required: ["iso", "services"],
  },
  handler: async (input) => {
    // TODO: query TimescaleDB
    return { ...(input as object), records: [], status: "stub" };
  },
};

export const detectAnomaly: ToolDefinition = {
  name: "detect_anomaly",
  description: "Detect statistical anomalies in price time series (z-score based)",
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
    // TODO: query TimescaleDB + compute z-score
    return { isAnomaly: false, sigma: 0, currentPrice: 0, historicalMean: 0, status: "stub" };
  },
};

export const parseIsoDocument: ToolDefinition = {
  name: "parse_iso_document",
  description: "Parse unstructured ISO documents (outage notices, rule changes, settlement PDFs)",
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
  handler: async (input) => {
    // TODO: fetch + pass to LLM parser
    return { parsed: {}, rawText: "", status: "stub" };
  },
};

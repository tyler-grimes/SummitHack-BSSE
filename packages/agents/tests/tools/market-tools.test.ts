import { describe, it, expect, vi, beforeEach } from "vitest";

// vi.mock is hoisted to the top of the file; use vi.hoisted to declare mocks
// that are referenced inside the factory without triggering TDZ errors.
const { mockQueryLmpHistory, mockQueryAncillaryPrices } = vi.hoisted(() => ({
  mockQueryLmpHistory: vi.fn(),
  mockQueryAncillaryPrices: vi.fn(),
}));

vi.mock("../../src/db/timescale.js", () => ({
  queryLmpHistory: mockQueryLmpHistory,
  queryAncillaryPrices: mockQueryAncillaryPrices,
}));

import {
  fetchRealtimeLmp,
  fetchAncillaryPrices,
  detectAnomaly,
  parseIsoDocument,
} from "../../src/tools/market-tools.js";

// Helper to make a Date from an ISO string
function d(iso: string): Date {
  return new Date(iso);
}

describe("market-tools", () => {
  beforeEach(() => {
    mockQueryLmpHistory.mockReset();
    mockQueryAncillaryPrices.mockReset();
  });

  // --- fetch_realtime_lmp ---

  describe("fetch_realtime_lmp", () => {
    it("calls queryLmpHistory for each node with the correct arguments", async () => {
      mockQueryLmpHistory.mockResolvedValue([]);

      await fetchRealtimeLmp.handler({ iso: "ERCOT", nodes: ["HB_NORTH", "HB_SOUTH"], lookbackMinutes: 30 });

      expect(mockQueryLmpHistory).toHaveBeenCalledTimes(2);
      expect(mockQueryLmpHistory).toHaveBeenCalledWith("ERCOT", "HB_NORTH", 30);
      expect(mockQueryLmpHistory).toHaveBeenCalledWith("ERCOT", "HB_SOUTH", 30);
    });

    it("uses default lookbackMinutes of 60 when not specified", async () => {
      mockQueryLmpHistory.mockResolvedValue([]);

      await fetchRealtimeLmp.handler({ iso: "PJM", nodes: ["AEP-DAYTON"] });

      expect(mockQueryLmpHistory).toHaveBeenCalledWith("PJM", "AEP-DAYTON", 60);
    });

    it("returns sorted records with ISO timestamp strings (not Date objects)", async () => {
      // Return rows out of order to test sorting
      mockQueryLmpHistory.mockImplementation((_iso: string, node: string) => {
        if (node === "HB_NORTH") {
          return Promise.resolve([
            { time: d("2024-01-01T02:00:00Z"), lmp: 50 },
            { time: d("2024-01-01T01:00:00Z"), lmp: 45 },
          ]);
        }
        return Promise.resolve([{ time: d("2024-01-01T01:30:00Z"), lmp: 48 }]);
      });

      const result = (await fetchRealtimeLmp.handler({
        iso: "ERCOT",
        nodes: ["HB_NORTH", "HB_WEST"],
        lookbackMinutes: 60,
      })) as { records: Array<{ node: string; time: string; lmp: number }> };

      // All times should be ISO strings
      for (const rec of result.records) {
        expect(typeof rec.time).toBe("string");
        // Must parse as valid ISO-8601
        expect(Number.isNaN(new Date(rec.time).getTime())).toBe(false);
      }

      // Records must be sorted ascending by time
      for (let i = 1; i < result.records.length; i++) {
        expect(result.records[i]!.time >= result.records[i - 1]!.time).toBe(true);
      }
    });

    it("empty DB result returns { records: [] }", async () => {
      mockQueryLmpHistory.mockResolvedValue([]);

      const result = (await fetchRealtimeLmp.handler({
        iso: "ERCOT",
        nodes: ["HB_NORTH"],
        lookbackMinutes: 60,
      })) as { records: unknown[] };

      expect(result.records).toHaveLength(0);
    });

    it("includes iso, nodes, and lookbackMinutes in the response envelope", async () => {
      mockQueryLmpHistory.mockResolvedValue([]);

      const result = (await fetchRealtimeLmp.handler({
        iso: "CAISO",
        nodes: ["TH_NP15_GEN-APND"],
        lookbackMinutes: 15,
      })) as { iso: string; nodes: string[]; lookbackMinutes: number };

      expect(result.iso).toBe("CAISO");
      expect(result.nodes).toEqual(["TH_NP15_GEN-APND"]);
      expect(result.lookbackMinutes).toBe(15);
    });
  });

  // --- fetch_ancillary_prices ---

  describe("fetch_ancillary_prices", () => {
    it("calls queryAncillaryPrices with correct iso, services, and lookbackMinutes", async () => {
      mockQueryAncillaryPrices.mockResolvedValue([]);

      await fetchAncillaryPrices.handler({ iso: "ERCOT", services: ["REG_UP", "SPIN"], lookbackMinutes: 120 });

      expect(mockQueryAncillaryPrices).toHaveBeenCalledOnce();
      expect(mockQueryAncillaryPrices).toHaveBeenCalledWith("ERCOT", ["REG_UP", "SPIN"], 120);
    });

    it("maps rows correctly (time → ISO string, preserves service/price_mw/total_mw)", async () => {
      const rawRow = {
        time: d("2024-03-15T10:00:00Z"),
        service: "REG_UP",
        price_mw: 12.5,
        total_mw: 350,
      };
      mockQueryAncillaryPrices.mockResolvedValue([rawRow]);

      const result = (await fetchAncillaryPrices.handler({
        iso: "ERCOT",
        services: ["REG_UP"],
        lookbackMinutes: 60,
      })) as { records: Array<{ time: string; service: string; price_mw: number; total_mw: number }> };

      expect(result.records).toHaveLength(1);
      const rec = result.records[0]!;
      expect(rec.time).toBe("2024-03-15T10:00:00.000Z");
      expect(rec.service).toBe("REG_UP");
      expect(rec.price_mw).toBe(12.5);
      expect(rec.total_mw).toBe(350);
    });

    it("returns empty records array when DB returns no rows", async () => {
      mockQueryAncillaryPrices.mockResolvedValue([]);

      const result = (await fetchAncillaryPrices.handler({
        iso: "PJM",
        services: ["SPIN"],
        lookbackMinutes: 60,
      })) as { records: unknown[] };

      expect(result.records).toHaveLength(0);
    });
  });

  // --- detect_anomaly ---

  describe("detect_anomaly", () => {
    it("< 2 rows returns isAnomaly: false with explanatory message", async () => {
      mockQueryLmpHistory.mockResolvedValue([{ time: d("2024-01-01T00:00:00Z"), lmp: 50 }]);

      const result = (await detectAnomaly.handler({ iso: "ERCOT", node: "HB_NORTH" })) as {
        isAnomaly: boolean;
        message: string;
        dataPoints: number;
      };

      expect(result.isAnomaly).toBe(false);
      expect(typeof result.message).toBe("string");
      expect(result.message.length).toBeGreaterThan(0);
      expect(result.dataPoints).toBe(1);
    });

    it("0 rows also returns isAnomaly: false (edge case)", async () => {
      mockQueryLmpHistory.mockResolvedValue([]);

      const result = (await detectAnomaly.handler({ iso: "ERCOT", node: "HB_NORTH" })) as {
        isAnomaly: boolean;
      };

      expect(result.isAnomaly).toBe(false);
    });

    it("price 4σ above mean returns isAnomaly: true", async () => {
      // history = [10, 10, 10, 10, 10] → mean=10, std=0 won't work
      // Use varied history to get std > 0
      // history: [10, 12, 8, 11, 9] → mean=10, variance=2, std≈1.414
      // current price: 10 + 4*1.414 ≈ 15.66 → sigma ≈ 4 > default threshold 3
      const historyRows = [10, 12, 8, 11, 9, 16].map((lmp, i) => ({
        time: d(`2024-01-01T0${i}:00:00Z`),
        lmp,
      }));
      mockQueryLmpHistory.mockResolvedValue(historyRows);

      const result = (await detectAnomaly.handler({
        iso: "ERCOT",
        node: "HB_NORTH",
        sigmaThreshold: 3.0,
      })) as { isAnomaly: boolean; sigma: number };

      expect(result.isAnomaly).toBe(true);
      expect(Math.abs(result.sigma)).toBeGreaterThan(3.0);
    });

    it("price within threshold returns isAnomaly: false", async () => {
      // history [10,10,10,10] + current 10.5 → sigma very low
      const rows = [10, 10, 10, 10, 10, 10.5].map((lmp, i) => ({
        time: d(`2024-01-01T0${i}:00:00Z`),
        lmp,
      }));
      mockQueryLmpHistory.mockResolvedValue(rows);

      const result = (await detectAnomaly.handler({
        iso: "ERCOT",
        node: "HB_NORTH",
        sigmaThreshold: 3.0,
      })) as { isAnomaly: boolean; sigma: number };

      expect(result.isAnomaly).toBe(false);
    });

    it("all same prices (std=0) returns sigma: 0, no divide-by-zero crash", async () => {
      const rows = [50, 50, 50, 50, 50, 50].map((lmp, i) => ({
        time: d(`2024-01-01T0${i}:00:00Z`),
        lmp,
      }));
      mockQueryLmpHistory.mockResolvedValue(rows);

      const result = (await detectAnomaly.handler({
        iso: "ERCOT",
        node: "HB_NORTH",
      })) as { isAnomaly: boolean; sigma: number; historicalStd: number };

      expect(result.sigma).toBe(0);
      expect(result.historicalStd).toBe(0);
      expect(result.isAnomaly).toBe(false);
    });

    it("uses lookbackHours * 60 for the DB query (default 24h → 1440 min)", async () => {
      mockQueryLmpHistory.mockResolvedValue([]);

      await detectAnomaly.handler({ iso: "ERCOT", node: "HB_NORTH" });

      expect(mockQueryLmpHistory).toHaveBeenCalledWith("ERCOT", "HB_NORTH", 24 * 60);
    });

    it("respects custom lookbackHours parameter", async () => {
      mockQueryLmpHistory.mockResolvedValue([]);

      await detectAnomaly.handler({ iso: "ERCOT", node: "HB_NORTH", lookbackHours: 6 });

      expect(mockQueryLmpHistory).toHaveBeenCalledWith("ERCOT", "HB_NORTH", 360);
    });

    it("response includes currentPrice, historicalMean, historicalStd, sigmaThreshold when data is sufficient", async () => {
      const rows = [40, 42, 38, 41, 39, 50].map((lmp, i) => ({
        time: d(`2024-01-01T0${i}:00:00Z`),
        lmp,
      }));
      mockQueryLmpHistory.mockResolvedValue(rows);

      const result = (await detectAnomaly.handler({ iso: "ERCOT", node: "HB_NORTH" })) as {
        currentPrice: number;
        historicalMean: number;
        historicalStd: number;
        sigmaThreshold: number;
        dataPoints: number;
      };

      expect(result.currentPrice).toBe(50);
      expect(typeof result.historicalMean).toBe("number");
      expect(typeof result.historicalStd).toBe("number");
      expect(result.sigmaThreshold).toBe(3.0);
      expect(result.dataPoints).toBe(6);
    });
  });

  // --- parse_iso_document ---

  describe("parse_iso_document", () => {
    it('returns status: "not_implemented" (stub behavior confirmed)', async () => {
      const result = (await parseIsoDocument.handler({
        source: "https://example.com/outage.pdf",
        docType: "outage_notice",
      })) as { status: string; parsed: unknown; rawText: string; message: string };

      expect(result.status).toBe("not_implemented");
    });

    it("returns empty parsed object and rawText", async () => {
      const result = (await parseIsoDocument.handler({
        source: "file:///some/path.pdf",
        docType: "settlement",
      })) as { parsed: Record<string, unknown>; rawText: string };

      expect(result.parsed).toEqual({});
      expect(result.rawText).toBe("");
    });

    it("returns a human-readable message field", async () => {
      const result = (await parseIsoDocument.handler({
        source: "https://example.com/rule.pdf",
        docType: "rule_change",
      })) as { message: string };

      expect(typeof result.message).toBe("string");
      expect(result.message.length).toBeGreaterThan(0);
    });
  });
});

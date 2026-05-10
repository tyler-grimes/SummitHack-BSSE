import { describe, it, expect } from "vitest";
import {
  generateDayLmp,
  buildPriceMap,
  iterateDates,
} from "../src/synthetic-lmp.js";

describe("generateDayLmp", () => {
  it("returns 24 intervals", () => {
    const date = new Date("2024-01-08T00:00:00Z"); // Monday
    expect(generateDayLmp(date)).toHaveLength(24);
  });

  it("timestamps are hourly and UTC", () => {
    const date = new Date("2024-01-08T00:00:00Z");
    const points = generateDayLmp(date);
    for (let h = 0; h < 24; h++) {
      expect(points[h]?.timestamp).toBe(`2024-01-08T${String(h).padStart(2, "0")}:00:00.000Z`);
    }
  });

  it("all prices are positive", () => {
    const date = new Date("2024-01-08T00:00:00Z");
    for (const p of generateDayLmp(date)) {
      expect(p.lmp).toBeGreaterThan(0);
    }
  });

  it("prices stay in plausible range (no negative, not absurdly high ignoring spikes)", () => {
    const date = new Date("2024-06-15T00:00:00Z");
    const nonSpikePoints = generateDayLmp(date).filter((p) => p.lmp < 200);
    for (const p of nonSpikePoints) {
      expect(p.lmp).toBeGreaterThan(0);
      expect(p.lmp).toBeLessThan(200);
    }
  });

  it("is deterministic for same date", () => {
    const date = new Date("2024-03-15T00:00:00Z");
    const a = generateDayLmp(date);
    const b = generateDayLmp(date);
    expect(a.map((p) => p.lmp)).toEqual(b.map((p) => p.lmp));
  });

  it("differs across dates", () => {
    const d1 = generateDayLmp(new Date("2024-01-01T00:00:00Z"));
    const d2 = generateDayLmp(new Date("2024-01-02T00:00:00Z"));
    const allSame = d1.every((p, i) => p.lmp === d2[i]?.lmp);
    expect(allSame).toBe(false);
  });

  it("weekends have lower average than weekdays", () => {
    const weekday = generateDayLmp(new Date("2024-01-08T00:00:00Z")); // Mon
    const weekend = generateDayLmp(new Date("2024-01-06T00:00:00Z")); // Sat
    const weekdayMean = weekday.reduce((s, p) => s + p.lmp, 0) / 24;
    const weekendMean = weekend.reduce((s, p) => s + p.lmp, 0) / 24;
    expect(weekdayMean).toBeGreaterThan(weekendMean);
  });
});

describe("buildPriceMap", () => {
  it("maps timestamps to lmp values", () => {
    const date = new Date("2024-01-08T00:00:00Z");
    const points = generateDayLmp(date);
    const map = buildPriceMap(points);
    expect(map.size).toBe(24);
    expect(map.get("2024-01-08T00:00:00.000Z")).toBe(points[0]?.lmp);
    expect(map.get("2024-01-08T23:00:00.000Z")).toBe(points[23]?.lmp);
  });
});

describe("iterateDates", () => {
  it("returns inclusive range", () => {
    const dates = iterateDates("2024-01-01", "2024-01-03");
    expect(dates).toHaveLength(3);
    expect(dates[0]?.toISOString().slice(0, 10)).toBe("2024-01-01");
    expect(dates[2]?.toISOString().slice(0, 10)).toBe("2024-01-03");
  });

  it("returns single date when start equals end", () => {
    expect(iterateDates("2024-06-15", "2024-06-15")).toHaveLength(1);
  });

  it("returns empty when end is before start", () => {
    expect(iterateDates("2024-01-10", "2024-01-05")).toHaveLength(0);
  });
});

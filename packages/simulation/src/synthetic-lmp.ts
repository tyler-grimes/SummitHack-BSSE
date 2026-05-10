// Hourly LMP shape relative to base price ($/MWh delta)
const HOURLY_SHAPE: number[] = [
  -10, -12, -12, -10, -6, 0, 8, 18, 22, 18, 10, 6,
  5, 5, 8, 16, 28, 32, 32, 26, 16, 10, 4, -6,
];

export interface LmpPoint {
  timestamp: string;
  lmp: number;
}

function makeRng(seed: number): () => number {
  let s = seed >>> 0;
  return (): number => {
    s = Math.imul(s, 1664525) + 1013904223;
    s >>>= 0;
    return s / 4294967296;
  };
}

export function generateDayLmp(date: Date, basePriceMwh = 35): LmpPoint[] {
  const dayOfWeek = date.getUTCDay();
  const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
  const base = basePriceMwh + (isWeekend ? -6 : 0);
  const seed = date.getUTCFullYear() * 10000 + (date.getUTCMonth() + 1) * 100 + date.getUTCDate();
  const rng = makeRng(seed);

  return Array.from({ length: 24 }, (_, h) => {
    const shape = HOURLY_SHAPE[h] ?? 0;
    const noise = (rng() - 0.5) * 12;
    // 1% chance of price spike per interval
    const spike = rng() < 0.01 ? rng() * 400 + 100 : 0;
    const lmp = base + shape + noise + spike;
    const ts = new Date(date);
    ts.setUTCHours(h, 0, 0, 0);
    return { timestamp: ts.toISOString(), lmp };
  });
}

export function buildPriceMap(points: LmpPoint[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const p of points) {
    map.set(p.timestamp, p.lmp);
  }
  return map;
}

export function iterateDates(startDate: string, endDate: string): Date[] {
  const dates: Date[] = [];
  const cur = new Date(`${startDate}T00:00:00Z`);
  const end = new Date(`${endDate}T00:00:00Z`);
  while (cur <= end) {
    dates.push(new Date(cur));
    cur.setUTCDate(cur.getUTCDate() + 1);
  }
  return dates;
}

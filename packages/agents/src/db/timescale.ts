import pg from "pg";

let pool: pg.Pool | null = null;

function getPool(): pg.Pool {
  if (!pool) {
    pool = new pg.Pool({
      connectionString:
        process.env["TIMESCALE_URL"] ??
        "postgres://energy:energy@localhost:5432/energy",
      max: 5,
      idleTimeoutMillis: 30_000,
    });
  }
  return pool;
}

export interface LmpRow {
  time: Date;
  lmp: number;
}

export interface AncillaryRow {
  time: Date;
  service: string;
  clearing_price: number;
  mileage: number | null;
}

export async function queryLmpHistory(
  iso: string,
  node: string,
  lookbackMinutes: number
): Promise<LmpRow[]> {
  const result = await getPool().query<LmpRow>(
    `SELECT time, lmp
     FROM lmp
     WHERE iso = $1 AND node = $2
       AND time >= NOW() - make_interval(mins => $3::int)
     ORDER BY time ASC`,
    [iso, node, lookbackMinutes]
  );
  return result.rows;
}

export async function queryAncillaryPrices(
  iso: string,
  services: string[],
  lookbackMinutes: number
): Promise<AncillaryRow[]> {
  const result = await getPool().query<AncillaryRow>(
    `SELECT time, service, clearing_price, mileage
     FROM ancillary_prices
     WHERE iso = $1 AND service = ANY($2)
       AND time >= NOW() - make_interval(mins => $3::int)
     ORDER BY time ASC`,
    [iso, services, lookbackMinutes]
  );
  return result.rows;
}

/**
 * Fetches actual hourly LMP for a given date/node from:
 *   1. TimescaleDB (seeded from GridStatus)
 *   2. ERCOT ESR API archive endpoint (requires ERCOT_API_KEY)
 *      GET  /archive/NP3-566-CD  → list archives, find docId for target date
 *      POST /archive/NP3-566-CD/download  {"docIds":[id]} → ZIP → CSV
 *   3. ERCOT MIS public HTML scraping (no auth)
 *   4. Synthetic fallback
 */

import https from "node:https";
import fs from "node:fs";
import { execSync } from "node:child_process";
import { createRequire } from "node:module";
import type { LmpPoint } from "./synthetic-lmp.js";
import { generateDayLmp } from "./synthetic-lmp.js";

const require = createRequire(import.meta.url);
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { Pool } = require("pg") as typeof import("pg");

const ESR_BASE = "https://api.ercot.com/api/public-data";
// NP3-566-CD = Historical RTM Load Zone and Hub Prices (15-min SPP)
const ESR_PRODUCT_RTM = "NP3-566-CD";

let _pool: import("pg").Pool | null = null;

function getPool(): import("pg").Pool {
  if (!_pool) {
    _pool = new Pool({
      host: process.env["POSTGRES_HOST"] ?? "localhost",
      port: Number(process.env["POSTGRES_PORT"] ?? 5432),
      database: process.env["POSTGRES_DB"] ?? "energy_trading",
      user: process.env["POSTGRES_USER"] ?? "postgres",
      password: process.env["POSTGRES_PASSWORD"] ?? "",
      max: 5,
      connectionTimeoutMillis: 3000,
      idleTimeoutMillis: 10000,
    });
  }
  return _pool;
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

interface RequestOptions {
  method?: "GET" | "POST";
  headers?: Record<string, string>;
  body?: string;
}

function httpsRequest(url: string, opts: RequestOptions = {}): Promise<{ status: number; body: Buffer }> {
  return new Promise((resolve, reject) => {
    const { method = "GET", headers = {}, body } = opts;
    const urlObj = new URL(url);
    const reqOpts: https.RequestOptions = {
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      method,
      headers: { "User-Agent": "energy-trading-bess/1.0", ...headers },
    };
    if (body) {
      reqOpts.headers = {
        ...reqOpts.headers,
        "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(body).toString(),
      };
    }
    const req = https.request(reqOpts, (res) => {
      const chunks: Buffer[] = [];
      res.on("data", (c: Buffer) => chunks.push(c));
      res.on("end", () => resolve({ status: res.statusCode ?? 0, body: Buffer.concat(chunks) }));
      res.on("error", reject);
    });
    req.on("error", reject);
    if (body) req.write(body);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// ZIP extraction (shell unzip — avoids adding adm-zip dependency)
// ---------------------------------------------------------------------------

function extractZipToString(zipBuf: Buffer): string | null {
  try {
    const tmpZip = `/tmp/ercot_lmp_${Date.now()}.zip`;
    const tmpDir = `/tmp/ercot_lmp_${Date.now()}`;
    fs.writeFileSync(tmpZip, zipBuf);
    execSync(`mkdir -p ${tmpDir} && unzip -q ${tmpZip} -d ${tmpDir}`, { stdio: "ignore" });
    const files = fs.readdirSync(tmpDir);
    const csvFile = files.find((f) => f.toLowerCase().endsWith(".csv"));
    if (!csvFile) return null;
    const content = fs.readFileSync(`${tmpDir}/${csvFile}`, "utf8");
    execSync(`rm -rf ${tmpZip} ${tmpDir}`, { stdio: "ignore" });
    return content;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// CSV parser: ERCOT RTM SPP format
// Columns (historical): DeliveryDate, DeliveryHour, DeliveryInterval,
//                       SettlementPoint, SettlementPointType,
//                       SettlementPointPrice
// ---------------------------------------------------------------------------

function parseErcotSppCsv(csv: string, node: string, date: Date): LmpPoint[] | null {
  const lines = csv
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0);

  if (lines.length < 2) return null;

  const header = (lines[0] ?? "")
    .split(",")
    .map((h) => h.replace(/"/g, "").trim().toLowerCase());

  const dateIdx = header.findIndex((h) => h.includes("deliverydate"));
  const hourIdx = header.findIndex((h) => h.includes("deliveryhour"));
  const nameIdx = header.findIndex(
    (h) => h.includes("settlementpoint") && !h.includes("type") && !h.includes("price")
  );
  const priceIdx = header.findIndex((h) => h.includes("settlementpointprice") || h.includes("hubavg"));

  if (dateIdx < 0 || hourIdx < 0 || nameIdx < 0 || priceIdx < 0) return null;

  const yyyy = date.getUTCFullYear();
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  const dateStr = `${yyyy}-${mm}-${dd}`;

  const hourlyPrices = new Map<number, number[]>();

  for (const line of lines.slice(1)) {
    const cols = line.split(",").map((c) => c.replace(/"/g, "").trim());
    const name = cols[nameIdx] ?? "";
    if (!name.toUpperCase().includes(node.toUpperCase())) continue;

    const rawDate = cols[dateIdx] ?? "";
    // Normalise MM/DD/YYYY → YYYY-MM-DD
    const normalized = rawDate.includes("/")
      ? rawDate.replace(/(\d+)\/(\d+)\/(\d+)/, "$3-$1-$2")
      : rawDate;
    if (!normalized.startsWith(dateStr)) continue;

    const hour = Number(cols[hourIdx] ?? "");
    const price = parseFloat(cols[priceIdx] ?? "");
    if (isNaN(hour) || isNaN(price)) continue;

    const bucket = hourlyPrices.get(hour) ?? [];
    bucket.push(price);
    hourlyPrices.set(hour, bucket);
  }

  if (hourlyPrices.size < 20) return null;

  const points: LmpPoint[] = [];
  for (let h = 1; h <= 24; h++) {
    const prices = hourlyPrices.get(h);
    if (!prices || prices.length === 0) continue;
    const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
    const ts = new Date(date);
    ts.setUTCHours(h - 1, 0, 0, 0); // ERCOT hour 1 = 00:00 UTC
    points.push({ timestamp: ts.toISOString(), lmp: avg });
  }

  return points.length >= 20 ? points : null;
}

// ---------------------------------------------------------------------------
// 1. DB fetch
// ---------------------------------------------------------------------------

async function fetchFromDb(date: Date, iso: string, node: string): Promise<LmpPoint[] | null> {
  const pool = getPool();
  const dayStart = new Date(date);
  dayStart.setUTCHours(0, 0, 0, 0);
  const dayEnd = new Date(date);
  dayEnd.setUTCHours(23, 59, 59, 999);

  try {
    const result = await pool.query<{ time: Date; lmp: number }>(
      `SELECT time_bucket('1 hour', time) AS time, AVG(lmp) AS lmp
       FROM lmp
       WHERE iso = $1 AND node = $2 AND time >= $3 AND time <= $4
       GROUP BY 1 ORDER BY 1`,
      [iso.toUpperCase(), node, dayStart, dayEnd]
    );
    if (result.rows.length < 20) return null;
    return result.rows.map((r) => ({ timestamp: r.time.toISOString(), lmp: Number(r.lmp) }));
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// 2. ERCOT ESR API (requires ERCOT_API_KEY)
//    GET  /archive/NP3-566-CD          → list archives with docId + friendlyName
//    POST /archive/NP3-566-CD/download  {"docIds":[id]} → ZIP
// ---------------------------------------------------------------------------

interface EsrArchive {
  docId: number;
  friendlyName: string;
  postDatetime: string;
}

async function fetchFromEsrApi(date: Date, node: string): Promise<LmpPoint[] | null> {
  const apiKey = process.env["ERCOT_API_KEY"];
  if (!apiKey) return null;

  const headers = { "Ocp-Apim-Subscription-Key": apiKey };

  try {
    // List archives — paginate if needed (default pageSize is usually 25)
    const listUrl = `${ESR_BASE}/archive/${ESR_PRODUCT_RTM}?size=200`;
    const listRes = await httpsRequest(listUrl, { headers });
    if (listRes.status !== 200) return null;

    interface ArchiveResponse { archives?: EsrArchive[] }
    const data = JSON.parse(listRes.body.toString()) as ArchiveResponse;
    const archives: EsrArchive[] = data.archives ?? [];

    // Match by date in friendlyName (format varies: "YYYY-MM-DD" or "YYYYMMDD")
    const yyyy = date.getUTCFullYear();
    const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(date.getUTCDate()).padStart(2, "0");
    const dateKey = `${yyyy}${mm}${dd}`;
    const dateKeyDash = `${yyyy}-${mm}-${dd}`;

    const match = archives.find((a) => {
      const fn = a.friendlyName ?? "";
      return fn.includes(dateKey) || fn.includes(dateKeyDash);
    });
    if (!match) return null;

    // Download the archive as ZIP
    const dlUrl = `${ESR_BASE}/archive/${ESR_PRODUCT_RTM}/download`;
    const dlRes = await httpsRequest(dlUrl, {
      method: "POST",
      headers,
      body: JSON.stringify({ docIds: [match.docId] }),
    });
    if (dlRes.status !== 200) return null;

    // Extract CSV from ZIP
    const csv = extractZipToString(dlRes.body);
    if (!csv) return null;

    return parseErcotSppCsv(csv, node, date);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// 3. ERCOT MIS public API (no auth, HTML scraping)
//    GET misapp/GetReports.do?reportTypeId=13061&startDate=MM/DD/YYYY
//    → HTML with doclookupId links → download ZIP
// ---------------------------------------------------------------------------

const MIS_BASE = "https://www.ercot.com";

function parseMisDocIds(html: string): number[] {
  const ids: number[] = [];
  const re = /doclookupId=(\d+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    const id = Number(m[1]);
    if (!isNaN(id)) ids.push(id);
  }
  return [...new Set(ids)];
}

async function fetchFromErcotMis(date: Date, node: string): Promise<LmpPoint[] | null> {
  try {
    const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
    const dd = String(date.getUTCDate()).padStart(2, "0");
    const yyyy = date.getUTCFullYear();

    const listUrl =
      `${MIS_BASE}/misapp/GetReports.do?reportTypeId=13061` +
      `&startDate=${mm}%2F${dd}%2F${yyyy}` +
      `&endDate=${mm}%2F${dd}%2F${yyyy}` +
      `&showall=true`;

    const listRes = await httpsRequest(listUrl);
    if (listRes.status !== 200) return null;

    const docIds = parseMisDocIds(listRes.body.toString());
    if (docIds.length === 0) return null;

    const dlUrl =
      `${MIS_BASE}/misdownload/servlets/mirDownload` +
      `?mimic_duns=000000000&doclookupId=${docIds[0]}`;

    const dlRes = await httpsRequest(dlUrl);
    if (dlRes.status !== 200) return null;

    const raw = dlRes.body;
    let csv: string;

    if (raw[0] === 0x50 && raw[1] === 0x4b) {
      // ZIP magic bytes
      const extracted = extractZipToString(raw);
      if (!extracted) return null;
      csv = extracted;
    } else {
      csv = raw.toString("utf8");
    }

    return parseErcotSppCsv(csv, node, date);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export async function fetchActualLmp(
  date: Date,
  iso: string,
  node: string,
  basePriceMwh = 35
): Promise<LmpPoint[]> {
  // 1. DB
  const dbResult = await fetchFromDb(date, iso, node);
  if (dbResult) return dbResult;

  if (iso.toUpperCase() === "ERCOT") {
    // 2. ESR API (key-authenticated, clean REST)
    const esrResult = await fetchFromEsrApi(date, node);
    if (esrResult) return esrResult;

    // 3. MIS public scraping (no auth)
    const misResult = await fetchFromErcotMis(date, node);
    if (misResult) return misResult;
  }

  // 4. Synthetic
  return generateDayLmp(date, basePriceMwh);
}

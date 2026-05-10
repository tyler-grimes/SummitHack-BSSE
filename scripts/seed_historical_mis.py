"""
Seed ERCOT RT hub LMP data (Jan 2025 – Mar 2026) via ERCOT MIS report 13061.

Annual ZIPs → 12 monthly Excel sheets each.
Downloads 2025 full year + 2026 YTD, filters 4 hubs, inserts to TimescaleDB.

Run from repo root:
  packages/data-pipeline/.venv/bin/python scripts/seed_historical_mis.py
"""

import asyncio
import io
import logging
import os
import sys
import zipfile
from datetime import datetime, timezone, timedelta

import httpx
import openpyxl
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages", "data-pipeline"))

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

from src.db import init_pool, close_pool, insert_lmp_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

HUBS = {"HB_NORTH", "HB_SOUTH", "HB_WEST", "HB_HOUSTON"}
HEADERS = {"User-Agent": "energy-trading-bess/1.0"}

# Annual bundles: doc_id → year
ANNUAL_BUNDLES = {
    2025: 1177737535,
    2026: 1222489654,
}

# Sheets to process per year
SHEETS_TO_PROCESS = {
    2025: ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    2026: ["Jan", "Feb", "Mar"],   # through March 2026 only
}

MONTH_NAME_TO_NUM = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def sheet_to_records(df: pd.DataFrame, year: int, month_name: str) -> list[dict]:
    """Parse one monthly sheet → LMP records."""
    month = MONTH_NAME_TO_NUM[month_name]

    # Normalise column names
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {c.lower().replace(" ", ""): c for c in df.columns}

    date_col  = col_map.get("deliverydate")
    hour_col  = col_map.get("deliveryhour")
    ivl_col   = col_map.get("deliveryinterval")
    name_col  = col_map.get("settlementpointname")
    price_col = col_map.get("settlementpointprice")

    if not all([date_col, hour_col, name_col, price_col]):
        log.warning("Sheet %s/%d missing columns: %s", month_name, year, list(df.columns))
        return []

    # Filter to our 4 hubs
    mask = df[name_col].isin(HUBS)
    df = df[mask].copy()
    if df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        try:
            hub   = str(row[name_col]).strip()
            hour  = int(row[hour_col])          # 1-24 (hour-ending)
            ivl   = int(row[ivl_col]) if ivl_col and pd.notna(row.get(ivl_col)) else 1  # 1-4
            price = float(row[price_col])

            # Parse delivery date from "MM/DD/YYYY" string
            raw_date = str(row[date_col]).strip()
            try:
                d = datetime.strptime(raw_date, "%m/%d/%Y")
            except ValueError:
                continue
            if d.year != year or d.month != month:
                continue  # skip any stray rows from adjacent months

            # Convert ERCOT hour-ending (1-24) + 15-min interval (1-4) → UTC
            # ERCOT uses CPT = CST (UTC-6) all year for settlement purposes
            hour_0 = hour - 1          # 0..23
            minute = (ivl - 1) * 15   # 0, 15, 30, 45
            cpt_naive = datetime(d.year, d.month, d.day, hour_0, minute, 0)
            utc_dt = cpt_naive + timedelta(hours=6)  # CST → UTC

            records.append({
                "timestamp": utc_dt.replace(tzinfo=timezone.utc).isoformat(),
                "iso": "ERCOT",
                "node": hub,
                "lmp": price,
                "energy": price,
                "congestion": 0.0,
                "loss": 0.0,
            })
        except (ValueError, TypeError, KeyError):
            continue

    return records


async def process_year(client: httpx.AsyncClient, year: int) -> int:
    doc_id = ANNUAL_BUNDLES[year]
    sheets = SHEETS_TO_PROCESS[year]
    total = 0

    log.info("Downloading %d annual bundle (doc_id=%d)...", year, doc_id)
    try:
        dl = await client.get(
            f"https://www.ercot.com/misdownload/servlets/mirDownload"
            f"?mimic_duns=000000000&doclookupId={doc_id}",
            timeout=300,
        )
        dl.raise_for_status()
    except Exception as e:
        log.error("Failed to download %d bundle: %s", year, e)
        return 0

    raw = dl.content
    log.info("%d bundle downloaded: %.1f MB", year, len(raw) / 1_048_576)

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xlsx_name = next(n for n in zf.namelist() if n.lower().endswith(".xlsx"))
            xlsx_data = zf.read(xlsx_name)
    except Exception as e:
        log.error("ZIP extract failed for %d: %s", year, e)
        return 0

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_data), read_only=True, data_only=True)
    available = wb.sheetnames

    for sheet_name in sheets:
        if sheet_name not in available:
            log.warning("%d: sheet '%s' not found (available: %s)", year, sheet_name, available)
            continue

        ws = wb[sheet_name]
        rows = list(ws.values)
        if not rows:
            log.warning("%d/%s: empty sheet", year, sheet_name)
            continue

        df = pd.DataFrame(rows[1:], columns=rows[0])
        records = sheet_to_records(df, year, sheet_name)

        if records:
            inserted = await insert_lmp_batch(records)
            total += inserted
            log.info("%d/%s: %d records inserted", year, sheet_name, len(records))
        else:
            log.info("%d/%s: no hub records", year, sheet_name)

    wb.close()
    return total


async def main() -> None:
    await init_pool()
    log.info("DB ready. Processing years: %s", list(ANNUAL_BUNDLES))

    grand_total = 0
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for year in sorted(ANNUAL_BUNDLES):
            n = await process_year(client, year)
            log.info("=== %d done: %d rows inserted ===", year, n)
            grand_total += n

    await close_pool()
    log.info("Complete. Total rows inserted: %d", grand_total)


if __name__ == "__main__":
    asyncio.run(main())

"""
Open-Meteo weather fetcher.

No API key required. Variables fetched per hour:
  temperature_2m    (°C)
  wind_speed_10m    (m/s)
  shortwave_radiation (W/m²)

Node locations use representative population-center lat/lon for each ISO hub/zone.
"""

import logging

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

# Lat/lon for known ISO hubs — virtual pricing points mapped to load-center cities.
NODE_LOCATIONS: dict[str, dict[str, tuple[float, float]]] = {
    "ERCOT": {
        "HB_NORTH":   (32.78, -97.30),   # Dallas-Fort Worth
        "HB_SOUTH":   (29.42, -98.49),   # San Antonio
        "HB_WEST":    (31.99, -102.08),  # Midland-Odessa
        "HB_HOUSTON": (29.76, -95.37),   # Houston
    },
    "CAISO": {
        "NP15": (37.77, -122.42),  # San Francisco
        "SP15": (34.05, -118.24),  # Los Angeles
        "ZP26": (36.74, -119.79),  # Fresno
    },
    "PJM": {
        "PJM-RTO": (40.44, -79.99),  # Pittsburgh
        "AEP":     (38.35, -81.63),  # Charleston WV
        "COMED":   (41.88, -87.63),  # Chicago
        "PECO":    (39.95, -75.17),  # Philadelphia
        "PSEG":    (40.72, -74.17),  # Newark NJ
    },
    "MISO": {
        "MISO.MNPL": (44.98, -93.27),  # Minneapolis
        "MISO.AMIL": (39.80, -89.65),  # Springfield IL
        "MISO.CONS": (42.33, -83.05),  # Detroit
    },
    "NYISO": {
        "CAPITL": (42.65, -73.75),  # Albany
        "NYC":    (40.71, -74.01),  # New York City
        "WEST":   (43.04, -76.14),  # Syracuse
    },
    "ISONE": {
        "NEPOOL": (42.36, -71.06),  # Boston
        "CT":     (41.76, -72.68),  # Hartford
        "ME":     (44.31, -69.78),  # Augusta ME
    },
    "SPP": {
        "SPP":    (35.47, -97.52),  # Oklahoma City
    },
}

_HISTORY_URL = "https://archive-api.open-meteo.com/v1/archive"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
_VARIABLES = "temperature_2m,wind_speed_10m,shortwave_radiation"


def get_node_location(iso: str, node: str) -> tuple[float, float] | None:
    return NODE_LOCATIONS.get(iso.upper(), {}).get(node)


def _parse_response(data: dict) -> pd.DataFrame:
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    if not times:
        return pd.DataFrame(columns=["time", "temperature_2m", "wind_speed_10m", "shortwave_radiation"])
    return pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "temperature_2m": hourly.get("temperature_2m", [None] * len(times)),
        "wind_speed_10m": hourly.get("wind_speed_10m", [None] * len(times)),
        "shortwave_radiation": hourly.get("shortwave_radiation", [None] * len(times)),
    })


async def fetch_weather_history(
    lat: float, lon: float, start_date: str, end_date: str
) -> pd.DataFrame:
    """Fetch hourly ERA5 reanalysis weather for a date range. Returns UTC-indexed DataFrame."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": _VARIABLES,
        "timezone": "UTC",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_HISTORY_URL, params=params)
        resp.raise_for_status()
    return _parse_response(resp.json())


async def fetch_weather_forecast(lat: float, lon: float, hours: int = 48) -> pd.DataFrame:
    """Fetch hourly weather forecast for the next N hours. Returns UTC-indexed DataFrame."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": _VARIABLES,
        "forecast_days": max(2, (hours + 23) // 24),
        "timezone": "UTC",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(_FORECAST_URL, params=params)
        resp.raise_for_status()
    df = _parse_response(resp.json())
    now = pd.Timestamp.now(tz="UTC").floor("h")
    return df[df["time"] >= now].head(hours).reset_index(drop=True)

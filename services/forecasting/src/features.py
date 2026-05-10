import math

import pandas as pd


def build_features(
    df: pd.DataFrame,
    weather_df: pd.DataFrame | None = None,
    grid_state_df: pd.DataFrame | None = None,
    gas_price_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True)

    out["hour"] = out["time"].dt.hour.astype(float)
    out["day_of_week"] = out["time"].dt.dayofweek.astype(float)
    out["day_of_year"] = out["time"].dt.dayofyear.astype(float)
    out["month"] = out["time"].dt.month.astype(float)
    out["is_weekend"] = (out["time"].dt.dayofweek >= 5).astype(float)
    out["hour_x_weekend"] = out["hour"] * out["is_weekend"]

    # Cyclical encodings: avoids the artificial discontinuity at wrap-around
    # (e.g. hour 23 → 0 looks like a large jump in raw integer space).
    out["hour_sin"] = (out["hour"] * (2.0 * math.pi / 24.0)).apply(math.sin)
    out["hour_cos"] = (out["hour"] * (2.0 * math.pi / 24.0)).apply(math.cos)
    out["month_sin"] = (out["month"] * (2.0 * math.pi / 12.0)).apply(math.sin)
    out["month_cos"] = (out["month"] * (2.0 * math.pi / 12.0)).apply(math.cos)
    out["dow_sin"] = (out["day_of_week"] * (2.0 * math.pi / 7.0)).apply(math.sin)
    out["dow_cos"] = (out["day_of_week"] * (2.0 * math.pi / 7.0)).apply(math.cos)

    # hour × month interaction: 4pm in July (AC peak) ≠ 4pm in January (heat peak).
    # Captures seasonal regime differences that cyclical encodings alone cannot express.
    out["hour_x_month"] = out["hour"] * out["month"]

    # Detect data frequency so lags represent real time regardless of resolution.
    sorted_times = out["time"].sort_values()
    median_td = sorted_times.diff().median()
    median_minutes = median_td.total_seconds() / 60 if pd.notna(median_td) else 60.0
    iph = max(1, round(60 / median_minutes))

    out["lag_1h"]   = out["lmp"].shift(1   * iph)
    out["lag_2h"]   = out["lmp"].shift(2   * iph)
    out["lag_4h"]   = out["lmp"].shift(4   * iph)
    out["lag_24h"]  = out["lmp"].shift(24  * iph)
    out["lag_48h"]  = out["lmp"].shift(48  * iph)
    out["lag_72h"]  = out["lmp"].shift(72  * iph)
    out["lag_168h"] = out["lmp"].shift(168 * iph).fillna(out["lmp"].shift(24 * iph))

    # Shift by 1 before rolling to prevent look-ahead: the rolling window at
    # time t must only use data up to t-1, not the current observation.
    shifted_lmp = out["lmp"].shift(1)
    win_24h = 24 * iph
    win_7d  = 168 * iph
    win_6h  = 6  * iph
    out["rolling_mean_24h"] = shifted_lmp.rolling(win_24h, min_periods=win_24h).mean()
    out["rolling_std_24h"]  = shifted_lmp.rolling(win_24h, min_periods=win_24h).std().fillna(0.0)
    out["rolling_mean_7d"]  = shifted_lmp.rolling(win_7d,  min_periods=win_24h).mean()
    out["rolling_std_7d"]   = shifted_lmp.rolling(win_7d,  min_periods=win_24h).std().fillna(0.0)

    # ── Intraday momentum features ────────────────────────────────────────────
    # Short rolling std: captures intraday volatility regime.
    # High 6h std at hour 10 → elevated spread day → optimizer should dispatch.
    out["rolling_std_6h"] = shifted_lmp.rolling(win_6h, min_periods=max(1, win_6h // 2)).std().fillna(0.0)

    # lag_1h × hour: encodes "price level at this time of day".
    # $40 at hour 6 (pre-peak) predicts a higher afternoon than $40 at hour 20.
    out["lag1h_x_hour"] = out["lag_1h"] * out["hour"]

    # Price momentum: rate of change over last 3 hours (signed).
    # Rising prices → afternoon peak incoming; falling → oversupply.
    out["lmp_momentum_3h"] = out["lmp"].shift(1 * iph) - out["lmp"].shift(4 * iph)

    # Intraday min/max so far (using shifted values — no look-ahead).
    # Tells the model how wide the spread has already been today.
    date_key = out["time"].dt.date
    out["intraday_min_so_far"] = (
        shifted_lmp.groupby(date_key, group_keys=False)
        .transform(lambda s: s.expanding().min())
        .bfill()
    )
    out["intraday_max_so_far"] = (
        shifted_lmp.groupby(date_key, group_keys=False)
        .transform(lambda s: s.expanding().max())
        .bfill()
    )
    out["intraday_spread_so_far"] = out["intraday_max_so_far"] - out["intraday_min_so_far"]

    # Merge hourly weather onto LMP rows via floor-to-hour bucket.
    if weather_df is not None and not weather_df.empty:
        out["_h"] = out["time"].dt.floor("h")
        w = weather_df.copy()
        w["_h"] = pd.to_datetime(w["time"], utc=True).dt.floor("h")
        w = w[["_h", "temperature_2m", "wind_speed_10m", "shortwave_radiation"]]
        out = out.merge(w, on="_h", how="left").drop(columns=["_h"])
        # Forward-fill sparse gaps (e.g. DST boundary, missing API rows)
        for col in ("temperature_2m", "wind_speed_10m", "shortwave_radiation"):
            out[col] = out[col].ffill().bfill()
    else:
        out["temperature_2m"] = float("nan")
        out["wind_speed_10m"] = float("nan")
        out["shortwave_radiation"] = float("nan")

    # Named weather features + demand-proxy signals.
    out["weather_temp_c"]    = out["temperature_2m"].fillna(20.0)
    out["weather_wind_ms"]   = out["wind_speed_10m"].fillna(3.0)
    out["weather_solar_wm2"] = out["shortwave_radiation"].fillna(0.0)
    out["weather_hdd"]       = (18.0 - out["weather_temp_c"]).clip(lower=0.0)
    out["weather_cdd"]       = (out["weather_temp_c"] - 18.0).clip(lower=0.0)
    out = out.drop(columns=["temperature_2m", "wind_speed_10m", "shortwave_radiation"], errors="ignore")

    # Merge ERCOT grid-state signals: wind/solar generation and load vs forecast deviation.
    # These are the primary spike predictors — wind drop + load above forecast → spike.
    if grid_state_df is not None and not grid_state_df.empty:
        out["_h"] = out["time"].dt.floor("h")
        gs = grid_state_df.copy()
        gs["_h"] = pd.to_datetime(gs["time"], utc=True).dt.floor("h")
        gs_cols = [c for c in ["_h", "wind_actual_mw", "load_forecast_mw", "load_actual_mw", "solar_actual_mw"] if c in gs.columns]
        gs = gs[gs_cols]
        out = out.merge(gs, on="_h", how="left").drop(columns=["_h"])
        for col in ("wind_actual_mw", "load_forecast_mw", "load_actual_mw", "solar_actual_mw"):
            if col in out.columns:
                out[col] = out[col].ffill().bfill()
            else:
                out[col] = float("nan")
    else:
        out["wind_actual_mw"]   = float("nan")
        out["load_forecast_mw"] = float("nan")
        out["load_actual_mw"]   = float("nan")
        out["solar_actual_mw"]  = float("nan")

    # load_deviation_mw: positive = demand above forecast → price spike risk.
    out["load_deviation_mw"] = out["load_actual_mw"] - out["load_forecast_mw"]

    # net_load_mw: thermal residual after renewables. Proxy for reserve margin —
    # when net load is high relative to thermal capacity, scarcity pricing follows.
    out["net_load_mw"] = out["load_actual_mw"] - out["wind_actual_mw"] - out["solar_actual_mw"]

    # renewable_penetration: fraction of load served by wind + solar.
    # Sudden drops from high penetration (e.g. wind collapse at 60% share) are
    # the strongest leading indicator of RT price spikes in ERCOT.
    load = out["load_actual_mw"].replace(0, float("nan"))
    out["renewable_penetration"] = (out["wind_actual_mw"] + out["solar_actual_mw"]) / load

    # wind_ramp_mw: rate of change in wind generation. A sudden 3 GW drop in one hour
    # is the single strongest leading indicator of an RT price spike in ERCOT.
    # Use shift(1) to avoid look-ahead (ramp at t uses wind[t-1] → wind[t]).
    out["wind_ramp_mw"] = out["wind_actual_mw"] - out["wind_actual_mw"].shift(1)

    # solar_ramp_mw: captures the evening ramp-down (duck curve tail) which drives
    # the 4-7pm price spike as solar drops and gas must ramp fast to compensate.
    out["solar_ramp_mw"] = out["solar_actual_mw"] - out["solar_actual_mw"].shift(1)

    # Merge daily Henry Hub gas price — broadcast to all hours of each day.
    # Gas sets the marginal price in ERCOT ~70% of hours; a price spike shifts
    # the entire LMP curve up.
    if gas_price_df is not None and not gas_price_df.empty:
        gp = gas_price_df.copy()
        gp["_d"] = pd.to_datetime(gp["date"]).dt.tz_localize("UTC").dt.normalize()
        gp = gp[["_d", "henry_hub"]].drop_duplicates("_d")
        out["_d"] = out["time"].dt.normalize()
        out = out.merge(gp, on="_d", how="left").drop(columns=["_d"])
        # Forward-fill weekends/holidays when EIA has no quote
        out["henry_hub"] = out["henry_hub"].ffill().bfill()
    else:
        out["henry_hub"] = float("nan")

    out = out.dropna(subset=[
        "lag_1h", "lag_2h", "lag_4h", "lag_24h", "lag_48h", "lag_72h",
        "rolling_mean_24h", "rolling_std_24h",
    ])
    return out.reset_index(drop=True)

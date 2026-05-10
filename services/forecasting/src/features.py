import pandas as pd


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True)

    out["hour"] = out["time"].dt.hour.astype(float)
    out["day_of_week"] = out["time"].dt.dayofweek.astype(float)
    out["month"] = out["time"].dt.month.astype(float)
    out["is_weekend"] = (out["time"].dt.dayofweek >= 5).astype(float)

    # Detect data frequency so lags represent real time regardless of resolution.
    # e.g. 5-min data → iph=12; hourly data → iph=1.
    sorted_times = out["time"].sort_values()
    median_td = sorted_times.diff().median()
    median_minutes = median_td.total_seconds() / 60 if pd.notna(median_td) else 60.0
    iph = max(1, round(60 / median_minutes))  # intervals per hour

    out["lag_1h"]   = out["lmp"].shift(1  * iph)
    out["lag_2h"]   = out["lmp"].shift(2  * iph)
    out["lag_4h"]   = out["lmp"].shift(4  * iph)
    out["lag_24h"]  = out["lmp"].shift(24 * iph)
    out["lag_48h"]  = out["lmp"].shift(48 * iph)  # 2-day lag; replaces 7-day until >90 days history
    out["lag_168h"] = out["lmp"].shift(168 * iph).fillna(out["lmp"].shift(24 * iph))  # soft fallback

    out["rolling_mean_24h"] = out["lmp"].rolling(24 * iph, min_periods=1).mean()
    out["rolling_std_24h"]  = out["lmp"].rolling(24 * iph, min_periods=1).std().fillna(0.0)

    out = out.dropna(subset=["lag_1h", "lag_2h", "lag_4h", "lag_24h", "lag_48h"])
    return out.reset_index(drop=True)

import pandas as pd


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"], utc=True)

    out["hour"] = out["time"].dt.hour.astype(float)
    out["day_of_week"] = out["time"].dt.dayofweek.astype(float)
    out["month"] = out["time"].dt.month.astype(float)
    out["is_weekend"] = (out["time"].dt.dayofweek >= 5).astype(float)

    out["lag_1h"] = out["lmp"].shift(1)
    out["lag_2h"] = out["lmp"].shift(2)
    out["lag_4h"] = out["lmp"].shift(4)
    out["lag_24h"] = out["lmp"].shift(24)
    out["lag_168h"] = out["lmp"].shift(168)

    out["rolling_mean_24h"] = out["lmp"].rolling(24, min_periods=1).mean()
    out["rolling_std_24h"] = out["lmp"].rolling(24, min_periods=1).std().fillna(0.0)

    out = out.dropna(subset=["lag_1h", "lag_2h", "lag_4h", "lag_24h", "lag_168h"])
    return out.reset_index(drop=True)

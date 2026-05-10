-- ERCOT grid-state signals: wind generation (actual + forecast) and system load.
-- Hourly resolution matching the MIS public reports (13028, 13101).
-- Used as features in the price forecasting model — wind drop + load spike → price spike.

CREATE TABLE IF NOT EXISTS ercot_grid_state (
    time                TIMESTAMPTZ     NOT NULL,   -- hour-start UTC
    wind_actual_mw      DOUBLE PRECISION,            -- fuel_mix.wind actual generation (MW)
    load_forecast_mw    DOUBLE PRECISION,            -- DA load forecast (MW); load_deviation = actual - forecast
    load_actual_mw      DOUBLE PRECISION,            -- actual system load (MW)
    solar_actual_mw     DOUBLE PRECISION             -- fuel_mix.solar actual generation (MW)
);

SELECT create_hypertable('ercot_grid_state', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS ercot_grid_state_time ON ercot_grid_state (time DESC);

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- LMP prices (all ISOs)
CREATE TABLE IF NOT EXISTS lmp (
    time            TIMESTAMPTZ     NOT NULL,
    iso             TEXT            NOT NULL,
    node            TEXT            NOT NULL,
    lmp             DOUBLE PRECISION NOT NULL,
    energy          DOUBLE PRECISION,
    congestion      DOUBLE PRECISION,
    loss            DOUBLE PRECISION
);

SELECT create_hypertable('lmp', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS lmp_iso_node_time ON lmp (iso, node, time DESC);

-- Ancillary service prices
CREATE TABLE IF NOT EXISTS ancillary_prices (
    time            TIMESTAMPTZ     NOT NULL,
    iso             TEXT            NOT NULL,
    service         TEXT            NOT NULL,
    clearing_price  DOUBLE PRECISION NOT NULL,
    mileage         DOUBLE PRECISION
);

SELECT create_hypertable('ancillary_prices', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS ancillary_iso_service_time ON ancillary_prices (iso, service, time DESC);

-- Battery state history
CREATE TABLE IF NOT EXISTS battery_state (
    time                        TIMESTAMPTZ     NOT NULL,
    asset_id                    TEXT            NOT NULL,
    soc_pct                     DOUBLE PRECISION NOT NULL,
    soc_mwh                     DOUBLE PRECISION NOT NULL,
    available_charge_mw         DOUBLE PRECISION NOT NULL,
    available_discharge_mw      DOUBLE PRECISION NOT NULL,
    temp_c                      DOUBLE PRECISION,
    cycle_count                 INTEGER
);

SELECT create_hypertable('battery_state', 'time', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS battery_asset_time ON battery_state (asset_id, time DESC);

-- Dispatch schedules (simulation output)
CREATE TABLE IF NOT EXISTS dispatch_schedules (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    asset_id        TEXT            NOT NULL,
    iso             TEXT            NOT NULL,
    horizon_start   TIMESTAMPTZ     NOT NULL,
    horizon_end     TIMESTAMPTZ     NOT NULL,
    solver_status   TEXT            NOT NULL,
    total_expected_revenue_dollars DOUBLE PRECISION,
    schedule_json   JSONB           NOT NULL
);

-- P&L tracking (simulation)
CREATE TABLE IF NOT EXISTS simulation_pnl (
    time                TIMESTAMPTZ     NOT NULL,
    asset_id            TEXT            NOT NULL,
    market              TEXT            NOT NULL,
    expected_revenue    DOUBLE PRECISION,
    actual_lmp          DOUBLE PRECISION,
    dispatch_mw         DOUBLE PRECISION
);

SELECT create_hypertable('simulation_pnl', 'time', if_not_exists => TRUE);

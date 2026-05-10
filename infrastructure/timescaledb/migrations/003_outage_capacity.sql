-- ERCOT hourly resource outage capacity: total MW offline by zone.
-- Source: ercot_hourly_resource_outage_capacity_reports via GridStatus.io
-- Used as a reserve-margin proxy feature: high outage MW + high load → spike risk.

CREATE TABLE IF NOT EXISTS ercot_outage_capacity (
    time                    TIMESTAMPTZ      NOT NULL,
    total_outage_mw         DOUBLE PRECISION,
    outage_mw_zone_north    DOUBLE PRECISION,
    outage_mw_zone_south    DOUBLE PRECISION,
    outage_mw_zone_west     DOUBLE PRECISION,
    outage_mw_zone_houston  DOUBLE PRECISION
);

SELECT create_hypertable('ercot_outage_capacity', 'time', if_not_exists => TRUE);
CREATE UNIQUE INDEX IF NOT EXISTS ercot_outage_capacity_time ON ercot_outage_capacity (time DESC);

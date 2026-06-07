-- Kardashev Data Platform — TimescaleDB schema
-- Run once against a fresh database:
--   psql $DATABASE_URL -f db/schema.sql

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- ---------------------------------------------------------------------------
-- Fuel mix  (5-min intervals per ISO per fuel type)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fuel_mix (
    ts          TIMESTAMPTZ     NOT NULL,
    iso         TEXT            NOT NULL,
    fuel_type   TEXT            NOT NULL,
    mw          DOUBLE PRECISION,
    CONSTRAINT  fuel_mix_pk PRIMARY KEY (ts, iso, fuel_type)
);
SELECT create_hypertable('fuel_mix', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS fuel_mix_iso_fuel ON fuel_mix (iso, fuel_type, ts DESC);

-- ---------------------------------------------------------------------------
-- LMP prices  (real-time 5-min + day-ahead hourly)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lmp (
    ts          TIMESTAMPTZ     NOT NULL,
    iso         TEXT            NOT NULL,
    node_id     TEXT            NOT NULL,
    node_name   TEXT,
    market      TEXT            NOT NULL,  -- 'RT' | 'DA'
    lmp         DOUBLE PRECISION,
    energy      DOUBLE PRECISION,
    congestion  DOUBLE PRECISION,
    loss        DOUBLE PRECISION,
    CONSTRAINT  lmp_pk PRIMARY KEY (ts, iso, node_id, market)
);
SELECT create_hypertable('lmp', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS lmp_iso_node ON lmp (iso, node_id, market, ts DESC);

-- ---------------------------------------------------------------------------
-- Load  (actual + forecast by zone)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS load_data (
    ts          TIMESTAMPTZ     NOT NULL,
    iso         TEXT            NOT NULL,
    zone        TEXT            NOT NULL,
    mw_actual   DOUBLE PRECISION,
    mw_forecast DOUBLE PRECISION,
    CONSTRAINT  load_pk PRIMARY KEY (ts, iso, zone)
);
SELECT create_hypertable('load_data', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS load_iso_zone ON load_data (iso, zone, ts DESC);

-- ---------------------------------------------------------------------------
-- Curtailment  (daily totals; hourly detail in curtailment_hourly)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS curtailment (
    date        DATE            NOT NULL,
    iso         TEXT            NOT NULL,
    solar_mwh   DOUBLE PRECISION DEFAULT 0,
    wind_mwh    DOUBLE PRECISION DEFAULT 0,
    total_mwh   DOUBLE PRECISION DEFAULT 0,
    updated_at  TIMESTAMPTZ     DEFAULT now(),
    CONSTRAINT  curtailment_pk PRIMARY KEY (date, iso)
);

CREATE TABLE IF NOT EXISTS curtailment_hourly (
    ts          TIMESTAMPTZ     NOT NULL,
    iso         TEXT            NOT NULL,
    hour        SMALLINT        NOT NULL,
    solar_mwh   DOUBLE PRECISION DEFAULT 0,
    wind_mwh    DOUBLE PRECISION DEFAULT 0,
    total_mwh   DOUBLE PRECISION DEFAULT 0,
    CONSTRAINT  curtailment_hourly_pk PRIMARY KEY (ts, iso, hour)
);
SELECT create_hypertable('curtailment_hourly', 'ts', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Interconnection queue  (snapshot table, overwritten on each fetch)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interconnection_queue (
    id              TEXT,
    iso             TEXT            NOT NULL,
    project_name    TEXT,
    county          TEXT,
    state           TEXT,
    fuel_type       TEXT,
    mw              DOUBLE PRECISION,
    status          TEXT,
    queue_date      DATE,
    withdrawal_date DATE,
    online_date     DATE,
    updated_at      TIMESTAMPTZ     DEFAULT now()
);
CREATE INDEX IF NOT EXISTS iq_iso ON interconnection_queue (iso, status, fuel_type);

-- ---------------------------------------------------------------------------
-- Generator reference  (static, refreshed weekly)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generators (
    gen_id          TEXT,
    iso             TEXT            NOT NULL,
    name            TEXT,
    fuel_type       TEXT,
    zone            TEXT,
    state           TEXT,
    capacity_mw     DOUBLE PRECISION,
    online_date     DATE,
    updated_at      TIMESTAMPTZ     DEFAULT now()
);
CREATE INDEX IF NOT EXISTS gen_iso ON generators (iso, fuel_type);

-- ---------------------------------------------------------------------------
-- Binding constraints  (MISO / CAISO / ISONE)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS binding_constraints (
    ts              TIMESTAMPTZ     NOT NULL,
    iso             TEXT            NOT NULL,
    market          TEXT            NOT NULL,  -- 'RT' | 'DA'
    constraint_name TEXT            NOT NULL,
    shadow_price    DOUBLE PRECISION,
    CONSTRAINT      bc_pk PRIMARY KEY (ts, iso, market, constraint_name)
);
SELECT create_hypertable('binding_constraints', 'ts', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Compression policies  (7-day chunks, compress older than 7 days)
-- ---------------------------------------------------------------------------
ALTER TABLE fuel_mix             SET (timescaledb.compress, timescaledb.compress_segmentby = 'iso,fuel_type');
ALTER TABLE lmp                  SET (timescaledb.compress, timescaledb.compress_segmentby = 'iso,node_id,market');
ALTER TABLE load_data            SET (timescaledb.compress, timescaledb.compress_segmentby = 'iso,zone');
ALTER TABLE curtailment_hourly   SET (timescaledb.compress, timescaledb.compress_segmentby = 'iso');
ALTER TABLE binding_constraints  SET (timescaledb.compress, timescaledb.compress_segmentby = 'iso,market');

SELECT add_compression_policy('fuel_mix',           INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('lmp',                INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('load_data',          INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('curtailment_hourly', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('binding_constraints',INTERVAL '7 days', if_not_exists => TRUE);

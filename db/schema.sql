-- Kardashev Data Platform — PostgreSQL schema (Railway-compatible)
-- Run once against a fresh database:
--   psql $DATABASE_URL -f db/schema.sql
--
-- TimescaleDB note: schema uses plain Postgres. Partitioning via BRIN indexes
-- on ts gives good range-query performance up to ~500M rows without hypertables.

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
-- BRIN for range scans; btree for point lookups by ISO
CREATE INDEX IF NOT EXISTS fuel_mix_ts_brin   ON fuel_mix USING BRIN (ts);
CREATE INDEX IF NOT EXISTS fuel_mix_iso_fuel  ON fuel_mix (iso, fuel_type, ts DESC);

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
CREATE INDEX IF NOT EXISTS lmp_ts_brin   ON lmp USING BRIN (ts);
CREATE INDEX IF NOT EXISTS lmp_iso_node  ON lmp (iso, node_id, market, ts DESC);

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
CREATE INDEX IF NOT EXISTS load_ts_brin   ON load_data USING BRIN (ts);
CREATE INDEX IF NOT EXISTS load_iso_zone  ON load_data (iso, zone, ts DESC);

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
CREATE INDEX IF NOT EXISTS curtailment_hourly_ts_brin ON curtailment_hourly USING BRIN (ts);

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
CREATE INDEX IF NOT EXISTS bc_ts_brin  ON binding_constraints USING BRIN (ts);
CREATE INDEX IF NOT EXISTS bc_iso      ON binding_constraints (iso, market, ts DESC);

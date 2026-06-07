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

-- ---------------------------------------------------------------------------
-- Generation forecast  (wind + solar actual vs. grid operator forecast)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gen_forecast (
    ts           TIMESTAMPTZ      NOT NULL,
    iso          TEXT             NOT NULL,
    fuel_type    TEXT             NOT NULL,   -- 'Wind' | 'Solar'
    mw_actual    DOUBLE PRECISION,
    mw_potential DOUBLE PRECISION,            -- WGRPP (wind) / PVGRPP (solar)
    CONSTRAINT   gen_forecast_pk PRIMARY KEY (ts, iso, fuel_type)
);
CREATE INDEX IF NOT EXISTS gf_ts_brin ON gen_forecast USING BRIN (ts);
CREATE INDEX IF NOT EXISTS gf_iso     ON gen_forecast (iso, fuel_type, ts DESC);

-- ---------------------------------------------------------------------------
-- Natural gas spot prices  (EIA Henry Hub + regional hubs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nat_gas_prices (
    ts           TIMESTAMPTZ      NOT NULL,
    hub          TEXT             NOT NULL,   -- 'Henry Hub', 'Algonquin', etc.
    price_usd    DOUBLE PRECISION,            -- $/MMBtu
    series_id    TEXT,
    CONSTRAINT   ngp_pk PRIMARY KEY (ts, hub)
);
CREATE INDEX IF NOT EXISTS ngp_ts_brin ON nat_gas_prices USING BRIN (ts);

-- ---------------------------------------------------------------------------
-- Battery storage  (CAISO 5-min charge/discharge)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS battery_storage (
    ts             TIMESTAMPTZ      NOT NULL,
    iso            TEXT             NOT NULL,
    mw_charging    DOUBLE PRECISION,          -- positive = charging (consuming)
    mw_discharging DOUBLE PRECISION,          -- positive = discharging (generating)
    mwh_state      DOUBLE PRECISION,          -- state of charge if available
    CONSTRAINT     batt_pk PRIMARY KEY (ts, iso)
);
CREATE INDEX IF NOT EXISTS batt_ts_brin ON battery_storage USING BRIN (ts);

-- ---------------------------------------------------------------------------
-- Behind-the-meter solar  (NYISO hourly actual vs. forecast)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS btm_solar (
    ts           TIMESTAMPTZ      NOT NULL,
    iso          TEXT             NOT NULL,
    mw_actual    DOUBLE PRECISION,
    mw_forecast  DOUBLE PRECISION,
    CONSTRAINT   btm_pk PRIMARY KEY (ts, iso)
);
CREATE INDEX IF NOT EXISTS btm_ts_brin ON btm_solar USING BRIN (ts);

-- ---------------------------------------------------------------------------
-- EIA weekly natural gas storage  (region-level Bcf)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gas_storage (
    ts           TIMESTAMPTZ      NOT NULL,   -- report week ending date
    region       TEXT             NOT NULL,   -- 'US Lower 48', 'East', 'Midwest', etc.
    bcf          DOUBLE PRECISION,            -- working gas in storage (Bcf)
    series_id    TEXT,
    CONSTRAINT   gst_pk PRIMARY KEY (ts, region)
);
CREATE INDEX IF NOT EXISTS gst_ts_brin ON gas_storage USING BRIN (ts);

-- ---------------------------------------------------------------------------
-- Capacity reserve margins  (ISO-level, sourced from PJM & ISONE APIs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reserve_margins (
    ts           TIMESTAMPTZ      NOT NULL,
    iso          TEXT             NOT NULL,
    required_pct DOUBLE PRECISION,           -- required reserve margin %
    actual_pct   DOUBLE PRECISION,           -- actual reserve margin %
    installed_mw DOUBLE PRECISION,
    peak_mw      DOUBLE PRECISION,
    CONSTRAINT   rsv_pk PRIMARY KEY (ts, iso)
);
CREATE INDEX IF NOT EXISTS rsv_ts_brin ON reserve_margins USING BRIN (ts);

-- ---------------------------------------------------------------------------
-- BPA real-time balancing area  (5-min wind, hydro, thermal, load)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bpa_balancesheet (
    ts                  TIMESTAMPTZ      NOT NULL PRIMARY KEY,
    load_mw             DOUBLE PRECISION,
    wind_mw             DOUBLE PRECISION,
    hydro_mw            DOUBLE PRECISION,
    thermal_mw          DOUBLE PRECISION,
    nuclear_mw          DOUBLE PRECISION,
    net_interchange_mw  DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS bpa_ts_brin ON bpa_balancesheet USING BRIN (ts);

-- ---------------------------------------------------------------------------
-- Grid-area temperature  (hourly, via Open-Meteo)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grid_temperature (
    ts           TIMESTAMPTZ      NOT NULL,
    iso          TEXT             NOT NULL,
    city         TEXT             NOT NULL,
    temp_f       DOUBLE PRECISION,
    humidity_pct DOUBLE PRECISION,
    wind_mph     DOUBLE PRECISION,
    CONSTRAINT   temp_pk PRIMARY KEY (ts, iso, city)
);
CREATE INDEX IF NOT EXISTS temp_ts_brin ON grid_temperature USING BRIN (ts);
CREATE INDEX IF NOT EXISTS temp_iso     ON grid_temperature (iso, ts DESC);

-- ---------------------------------------------------------------------------
-- EIA-923: Monthly net generation by state + fuel type
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monthly_generation (
    period       TEXT             NOT NULL,   -- "YYYY-MM"
    state        TEXT             NOT NULL,
    fuel_type    TEXT             NOT NULL,
    sector       TEXT,
    mwh          DOUBLE PRECISION,
    CONSTRAINT   mgen_pk PRIMARY KEY (period, state, fuel_type, sector)
);
CREATE INDEX IF NOT EXISTS mgen_period ON monthly_generation (period DESC, state, fuel_type);

-- ---------------------------------------------------------------------------
-- EIA-860: Annual installed generator capacity
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generator_capacity (
    period       TEXT             NOT NULL,   -- "YYYY"
    state        TEXT             NOT NULL,
    technology   TEXT             NOT NULL,
    fuel_type    TEXT,
    capacity_mw  DOUBLE PRECISION,
    CONSTRAINT   gcap_pk PRIMARY KEY (period, state, technology)
);
CREATE INDEX IF NOT EXISTS gcap_period ON generator_capacity (period DESC, state);

-- ---------------------------------------------------------------------------
-- EIA-861: Monthly retail electricity prices + sales
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retail_prices (
    period       TEXT             NOT NULL,   -- "YYYY-MM"
    state        TEXT             NOT NULL,
    sector       TEXT             NOT NULL,   -- RES, COM, IND, ALL
    price_cents_kwh DOUBLE PRECISION,
    sales_mwh    DOUBLE PRECISION,
    customers    DOUBLE PRECISION,
    CONSTRAINT   rp_pk PRIMARY KEY (period, state, sector)
);
CREATE INDEX IF NOT EXISTS rp_period ON retail_prices (period DESC, state, sector);

-- ---------------------------------------------------------------------------
-- EIA inter-regional interchange  (hourly net flows between BAs)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interchange (
    ts           TIMESTAMPTZ      NOT NULL,
    from_ba      TEXT             NOT NULL,   -- respondent / source BA
    to_ba        TEXT,                        -- fromba / neighbor (may be NULL for total)
    mw           DOUBLE PRECISION,            -- positive = export from from_ba
    CONSTRAINT   ix_pk PRIMARY KEY (ts, from_ba, to_ba)
);
CREATE INDEX IF NOT EXISTS ix_ts_brin ON interchange USING BRIN (ts);
CREATE INDEX IF NOT EXISTS ix_ba      ON interchange (from_ba, ts DESC);

-- Kardashev Data Platform schema (PostgreSQL / Railway-compatible)
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

-- ---------------------------------------------------------------------------
-- NRC daily reactor status
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nuclear_reactor_status (
    date        DATE             NOT NULL,
    unit        TEXT             NOT NULL,
    power_pct   DOUBLE PRECISION,
    CONSTRAINT  nrc_pk PRIMARY KEY (date, unit)
);
CREATE INDEX IF NOT EXISTS nrc_date ON nuclear_reactor_status (date DESC);
CREATE INDEX IF NOT EXISTS nrc_unit ON nuclear_reactor_status (unit, date DESC);

-- ---------------------------------------------------------------------------
-- EPA CAMPD hourly emissions (per generator)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plant_emissions (
    date               DATE             NOT NULL,
    hour               SMALLINT         NOT NULL,
    facility_id        TEXT             NOT NULL,
    facility_name      TEXT,
    unit_id            TEXT             NOT NULL,
    state              TEXT,
    gross_load_mw      DOUBLE PRECISION,
    so2_lbs            DOUBLE PRECISION,
    nox_lbs            DOUBLE PRECISION,
    co2_tons           DOUBLE PRECISION,
    heat_input_mmbtu   DOUBLE PRECISION,
    CONSTRAINT  emissions_pk PRIMARY KEY (date, hour, facility_id, unit_id)
);
CREATE INDEX IF NOT EXISTS emissions_date  ON plant_emissions (date DESC);
CREATE INDEX IF NOT EXISTS emissions_state ON plant_emissions (state, date DESC);
CREATE INDEX IF NOT EXISTS emissions_fac   ON plant_emissions (facility_id, date DESC);

-- ---------------------------------------------------------------------------
-- Carbon allowance auction results (RGGI + CA-WCI)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS carbon_allowances (
    auction_date          DATE             NOT NULL,
    program               TEXT             NOT NULL,   -- 'RGGI' | 'CA-WCI'
    settlement_price_usd  DOUBLE PRECISION,
    allowances_offered    INTEGER,
    allowances_sold       INTEGER,
    CONSTRAINT  ca_pk PRIMARY KEY (auction_date, program)
);
CREATE INDEX IF NOT EXISTS ca_program ON carbon_allowances (program, auction_date DESC);

-- ---------------------------------------------------------------------------
-- USBR reservoir storage (Western US hydro)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reservoir_storage (
    ts           TIMESTAMPTZ      NOT NULL,
    reservoir    TEXT             NOT NULL,
    storage_af   DOUBLE PRECISION,
    capacity_af  DOUBLE PRECISION,
    pct_full     DOUBLE PRECISION,
    CONSTRAINT   res_pk PRIMARY KEY (ts, reservoir)
);
CREATE INDEX IF NOT EXISTS res_ts_brin    ON reservoir_storage USING BRIN (ts);
CREATE INDEX IF NOT EXISTS res_reservoir  ON reservoir_storage (reservoir, ts DESC);

-- ---------------------------------------------------------------------------
-- USGS streamflow gauge readings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS streamflow (
    ts         TIMESTAMPTZ      NOT NULL,
    site_id    TEXT             NOT NULL,
    site_name  TEXT,
    flow_cfs   DOUBLE PRECISION,
    CONSTRAINT sf_pk PRIMARY KEY (ts, site_id)
);
CREATE INDEX IF NOT EXISTS sf_ts_brin ON streamflow USING BRIN (ts);
CREATE INDEX IF NOT EXISTS sf_site    ON streamflow (site_id, ts DESC);

-- ---------------------------------------------------------------------------
-- EIA power burn (gas consumed for electric generation)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS power_burn (
    period   TEXT             NOT NULL,   -- "YYYY-MM"
    state    TEXT             NOT NULL,
    value    DOUBLE PRECISION,            -- MMcf
    units    TEXT,
    CONSTRAINT pb_pk PRIMARY KEY (period, state)
);
CREATE INDEX IF NOT EXISTS pb_period ON power_burn (period DESC, state);

-- ---------------------------------------------------------------------------
-- EIA coal prices
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS coal_prices (
    period                   TEXT             NOT NULL,
    rank                     TEXT             NOT NULL,
    price_usd_per_short_ton  DOUBLE PRECISION,
    CONSTRAINT  cp_pk PRIMARY KEY (period, rank)
);
CREATE INDEX IF NOT EXISTS cp_period ON coal_prices (period DESC);

-- ---------------------------------------------------------------------------
-- EIA petroleum spot prices
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS petroleum_prices (
    ts          TIMESTAMPTZ      NOT NULL,
    product     TEXT             NOT NULL,
    price_usd   DOUBLE PRECISION,
    CONSTRAINT  pp_pk PRIMARY KEY (ts, product)
);
CREATE INDEX IF NOT EXISTS pp_ts_brin ON petroleum_prices USING BRIN (ts);
CREATE INDEX IF NOT EXISTS pp_product ON petroleum_prices (product, ts DESC);

-- ---------------------------------------------------------------------------
-- EIA STEO (Short-Term Energy Outlook) monthly forecasts
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS steo_forecasts (
    period     TEXT             NOT NULL,   -- "YYYY-MM"
    series_id  TEXT             NOT NULL,
    value      DOUBLE PRECISION,
    units      TEXT,
    CONSTRAINT steo_pk PRIMARY KEY (period, series_id)
);
CREATE INDEX IF NOT EXISTS steo_period ON steo_forecasts (period DESC);

-- ---------------------------------------------------------------------------
-- LMP node locations  (pricing nodes with lat/lng for map visualization)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lmp_nodes (
    node_id     TEXT             NOT NULL,
    iso         TEXT             NOT NULL,
    name        TEXT,
    lat         NUMERIC(9, 6),
    lng         NUMERIC(9, 6),
    zone        TEXT,
    voltage_kv  NUMERIC,
    CONSTRAINT  lmp_nodes_pk PRIMARY KEY (node_id, iso)
);
CREATE INDEX IF NOT EXISTS lmp_nodes_iso ON lmp_nodes (iso);

-- ---------------------------------------------------------------------------
-- Ancillary services
--   CAISO: DAM clearing prices ($/MW-hr) — NR, RD, RU, SR, RMD, RMU
--   ERCOT: real-time operational capacity (MW) — RegUp, RegDown, RRS, NSRS, ECRS
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ancillary_services (
    ts             TIMESTAMPTZ      NOT NULL,
    iso            TEXT             NOT NULL,
    market         TEXT             NOT NULL,    -- DAM | HASP | RTM
    region         TEXT,
    service_type   TEXT             NOT NULL,    -- RegUp | RegDown | Spinning | NonSpin | RRS | NSRS | ECRS | ...
    clearing_price DOUBLE PRECISION,             -- $/MW-hr (CAISO DAM)
    mw_awarded     DOUBLE PRECISION,             -- MW deployed / awarded (ERCOT)
    mw_available   DOUBLE PRECISION,             -- MW available / undeployed (ERCOT)
    CONSTRAINT ancillary_services_pk PRIMARY KEY (ts, iso, market, service_type)
);
CREATE INDEX IF NOT EXISTS as_iso_ts ON ancillary_services (iso, ts DESC);

-- ---------------------------------------------------------------------------
-- Generator outages
--   unit-level (CAISO) and aggregate (MISO) in one table.
--   granularity = 'unit' for per-generator rows, 'aggregate' for region-level.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS generator_outages (
    iso            TEXT             NOT NULL,
    outage_id      TEXT             NOT NULL,
    start_time     TIMESTAMPTZ      NOT NULL,
    end_time       TIMESTAMPTZ,
    resource_id    TEXT,
    resource_name  TEXT,
    outage_type    TEXT,            -- FORCED | PLANNED | UNPLANNED | DERATED
    nature_of_work TEXT,
    mw_derated     DOUBLE PRECISION,
    mw_capacity    DOUBLE PRECISION,
    region         TEXT,
    granularity    TEXT             NOT NULL DEFAULT 'unit',
    report_date    DATE,
    CONSTRAINT generator_outages_pk PRIMARY KEY (iso, outage_id, start_time)
);
CREATE INDEX IF NOT EXISTS go_iso_date   ON generator_outages (iso, report_date DESC);
CREATE INDEX IF NOT EXISTS go_active     ON generator_outages (iso, start_time, end_time);

-- ---------------------------------------------------------------------------
-- NREL NSRDB solar irradiance (hourly, 10 grid locations)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS solar_irradiance (
    ts        TIMESTAMPTZ      NOT NULL,
    location  TEXT             NOT NULL,
    lat       DOUBLE PRECISION,
    lon       DOUBLE PRECISION,
    ghi       DOUBLE PRECISION,
    dni       DOUBLE PRECISION,
    dhi       DOUBLE PRECISION,
    CONSTRAINT  si_pk PRIMARY KEY (ts, location)
);
CREATE INDEX IF NOT EXISTS si_ts_brin  ON solar_irradiance USING BRIN (ts);
CREATE INDEX IF NOT EXISTS si_location ON solar_irradiance (location, ts DESC);

-- ---------------------------------------------------------------------------
-- ERCOT large load interconnection queue (monthly snapshot from the Large Load
-- Working Group's "Large Load Interconnection Status Update" deck, posted to
-- the LLWG meeting calendar page as a chart-based PDF -- extracted via vision
-- LLM since the source has no structured table/CSV, see ingest/ercot_large_load.py)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ercot_large_load_snapshots (
    snapshot_month              DATE             NOT NULL,  -- month the chart data point represents
    report_date                 DATE,                       -- LLWG meeting / report publish date
    total_mw                    DOUBLE PRECISION,
    colocated_mw                DOUBLE PRECISION,
    standalone_mw                DOUBLE PRECISION,
    by_status                   JSONB,                      -- {"no_studies_submitted": mw, "under_ercot_review": mw, ...}
    by_size_bucket               JSONB,                      -- {"75-250mw": {"count": n, "mw": mw}, ...}
    by_type                      JSONB,                      -- {"data_center": {"pct": p, "mw": mw}, "crypto": {...}, ...}
    by_zone                      JSONB,                      -- {"lz_west": mw, "lz_north": mw, "other": mw}
    approved_to_energize_mw      DOUBLE PRECISION,           -- cumulative
    planning_studies_approved_mw DOUBLE PRECISION,           -- cumulative
    trailing_12mo                JSONB,                      -- {"2026-01": mw, "2026-02": mw, ...} from the deck's own "Past 12 Months" chart, used to cross-validate overlapping deck extractions during backfill
    source_url                   TEXT,
    extracted_at                 TIMESTAMPTZ      DEFAULT now(),
    CONSTRAINT ercot_large_load_snapshots_pk PRIMARY KEY (snapshot_month)
);
CREATE INDEX IF NOT EXISTS ells_month ON ercot_large_load_snapshots (snapshot_month DESC);
-- Added 2026-07-16 for the backfill's cross-deck validation; table already exists in prod, so ALTER (not just the inline column above) is what actually lands it there.
ALTER TABLE ercot_large_load_snapshots ADD COLUMN IF NOT EXISTS trailing_12mo JSONB;

-- ---------------------------------------------------------------------------
-- ERCOT GIS Report milestone history: monthly generation-interconnection-queue
-- snapshots (reportTypeId 15933), one row per project per month, so a
-- project's screening/IA/construction/energization dates can be tracked
-- across time instead of only seeing its current state. Ported from
-- interconnection-queue-tracker/services/fetcher/backfill_gis.py 2026-07-17;
-- see ingest/ercot_gis.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ercot_gis_snapshots (
    queue_id                     TEXT             NOT NULL,
    snapshot_month                TEXT             NOT NULL,  -- "YYYY-MM", from the GIS_Report filename
    project_name                  TEXT,
    gim_study_phase                TEXT,
    county                         TEXT,
    zone                            TEXT,
    projected_cod                   TEXT,                     -- free-text date as filed, parsed at query/analysis time
    fuel                             TEXT,
    technology                       TEXT,
    capacity_mw                       NUMERIC,
    screening_study_started            TEXT,
    screening_study_complete            TEXT,
    ia_signed                            TEXT,
    construction_start                    TEXT,
    construction_end                       TEXT,
    approved_for_energization               TEXT,
    approved_for_synchronization             TEXT,
    poi_location                            TEXT,            -- GIS "POI Location" text; for future geocoding (added 2026-08-02)
    fetched_at                                TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT ercot_gis_snapshots_pk PRIMARY KEY (queue_id, snapshot_month)
);
CREATE INDEX IF NOT EXISTS egs_month ON ercot_gis_snapshots (snapshot_month DESC);
CREATE INDEX IF NOT EXISTS egs_zone  ON ercot_gis_snapshots (zone);
CREATE INDEX IF NOT EXISTS egs_county ON ercot_gis_snapshots (county);

-- Additive column for DBs created before 2026-08-02 (CREATE TABLE IF NOT EXISTS
-- will not alter an existing table).
ALTER TABLE ercot_gis_snapshots ADD COLUMN IF NOT EXISTS poi_location TEXT;

-- ---------------------------------------------------------------------------
-- Precomputed timeline aggregates from ercot_gis_snapshots (median/mean
-- durations by zone and fuel type), refreshed after each monthly ingest --
-- see ingest/ercot_gis_timelines.py. Small table (dozens of rows), safe to
-- fully replace (DELETE+INSERT) on every refresh rather than upsert row by row.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ercot_gis_timelines (
    metric        TEXT             NOT NULL,  -- 'full_process_days' | 'build_phase_days' | 'cod_slip_days' | 'pending_years_in_queue'
    group_type    TEXT             NOT NULL,  -- 'zone' | 'fuel'
    group_value   TEXT             NOT NULL,  -- e.g. 'LZ_WEST', 'Solar'
    sample_count  INTEGER,
    median_days   DOUBLE PRECISION,
    mean_days     DOUBLE PRECISION,
    median_years  DOUBLE PRECISION,
    total_mw      DOUBLE PRECISION,           -- pending-queue rows: total pending MW. annual_energized_mw rows: MW/yr throughput (median_years there is the observed window length, not a duration)
    computed_at   TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT ercot_gis_timelines_pk PRIMARY KEY (metric, group_type, group_value)
);

-- ---------------------------------------------------------------------------
-- ERCOT load-zone stress proxy: monthly LMP-derived congestion indicators per
-- settlement-point load zone (LZ_WEST, LZ_NORTH, LZ_SOUTH, LZ_HOUSTON, etc.),
-- computed offline from the full 2019-> local LMP research history (a
-- separate database from this one -- see ingest/compute_ercot_zone_stats.py)
-- and pushed here as a small monthly aggregate. Coarse but honest: a stress
-- *proxy*, not a real congestion/OPF model -- disclose this on any page that
-- surfaces it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ercot_zone_stats (
    zone                    TEXT             NOT NULL,
    month                   DATE             NOT NULL,
    mean_rt_da_spread       DOUBLE PRECISION,           -- mean(RT hourly - DA hourly), $/MWh
    p95_rt_price            DOUBLE PRECISION,           -- 95th pct of 15-min RT price, $/MWh
    pct_hours_rt_over_100   DOUBLE PRECISION,           -- fraction of RT intervals with price > $100
    pct_hours_rt_negative   DOUBLE PRECISION,           -- fraction of RT intervals with price < $0
    rt_price_volatility     DOUBLE PRECISION,           -- stdev of 15-min RT price within the month
    sample_count            INTEGER,                    -- number of RT intervals behind this row
    computed_at             TIMESTAMPTZ      NOT NULL DEFAULT now(),
    CONSTRAINT ercot_zone_stats_pk PRIMARY KEY (zone, month)
);
CREATE INDEX IF NOT EXISTS ezs_month ON ercot_zone_stats (month DESC);

-- ---------------------------------------------------------------------------
-- Live forward test: day-ahead RT-DA spread forecasts (issued daily by the
-- forecasting repo's live_forecast.py) and their realized scores. Forecasts
-- are immutable once issued (insert ON CONFLICT DO NOTHING) -- that is the
-- whole point of a public track record.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS spread_forecast (
    ts        TIMESTAMPTZ      NOT NULL,   -- target hour, interval start UTC
    iso       TEXT             NOT NULL DEFAULT 'ERCOT',
    node_id   TEXT             NOT NULL,
    issued_at TIMESTAMPTZ      NOT NULL,   -- when the forecast was generated
    p10       DOUBLE PRECISION,
    p50       DOUBLE PRECISION,
    p90       DOUBLE PRECISION,
    da        DOUBLE PRECISION,            -- DA price known at issuance
    model     TEXT             NOT NULL,   -- part of the PK: v1 and v2 both issue live
    CONSTRAINT spread_forecast_pk PRIMARY KEY (ts, iso, node_id, model)
);
CREATE INDEX IF NOT EXISTS sf_issued ON spread_forecast (issued_at DESC);

CREATE TABLE IF NOT EXISTS forecast_scores (
    ts         TIMESTAMPTZ      NOT NULL,
    iso        TEXT             NOT NULL DEFAULT 'ERCOT',
    node_id    TEXT             NOT NULL,
    rt         DOUBLE PRECISION,           -- realized hourly RT (mean of 15-min)
    spread     DOUBLE PRECISION,           -- rt - da
    err_p50    DOUBLE PRECISION,           -- spread - p50
    covered    BOOLEAN,                    -- p10 <= spread <= p90
    side       SMALLINT,                   -- DART signal: +1 long RT, -1 short, 0 flat
    pnl        DOUBLE PRECISION,           -- side * spread - fee (0 if flat)
    model      TEXT             NOT NULL,  -- copied from spread_forecast at scoring time
    cooldown   BOOLEAN          DEFAULT false, -- true if forced flat by the post-large-move cooldown rule (see pipeline/score_forecasts.py), regardless of what P10/P90 said
    scored_at  TIMESTAMPTZ      DEFAULT now(),
    CONSTRAINT forecast_scores_pk PRIMARY KEY (ts, iso, node_id, model)
);
CREATE INDEX IF NOT EXISTS fs_ts ON forecast_scores (ts DESC);
-- 2026-07-09: added model column for the v1/v2 track-record split.
-- 2026-07-10: widened both PKs to (ts, iso, node_id, model) so v1 and v2 can
-- both issue/score live for the same hour instead of one silently overwriting
-- the other via ON CONFLICT. ALTER for pre-existing tables:
--   ALTER TABLE spread_forecast DROP CONSTRAINT spread_forecast_pk;
--   ALTER TABLE spread_forecast ADD CONSTRAINT spread_forecast_pk PRIMARY KEY (ts, iso, node_id, model);
--   ALTER TABLE forecast_scores DROP CONSTRAINT forecast_scores_pk;
--   ALTER TABLE forecast_scores ADD CONSTRAINT forecast_scores_pk PRIMARY KEY (ts, iso, node_id, model);
-- 2026-07-25: added cooldown column (post-large-move trade suppression flag).
-- ALTER for pre-existing tables:
--   ALTER TABLE forecast_scores ADD COLUMN IF NOT EXISTS cooldown BOOLEAN DEFAULT false;
CREATE INDEX IF NOT EXISTS fs_model ON forecast_scores (model, ts DESC);

-- ---------------------------------------------------------------------------
-- Public accuracy tracker for ERCOT's OWN official day-ahead load forecast
-- (EIA-930 DF series) vs realized load (D series) -- not our model, scoring
-- the grid operator's published forecast. Same immutable-scoring pattern as
-- forecast_scores/spread_forecast. Backfillable immediately: both series
-- already exist for the full 2019-> history in ercot_features.parquet.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS load_forecast_scores (
    ts             TIMESTAMPTZ      NOT NULL,
    iso            TEXT             NOT NULL DEFAULT 'ERCOT',
    forecast_load  DOUBLE PRECISION NOT NULL,  -- EIA-930 DF series, day-ahead
    actual_load    DOUBLE PRECISION NOT NULL,  -- EIA-930 D series, realized
    err            DOUBLE PRECISION,           -- actual - forecast
    pct_err        DOUBLE PRECISION,           -- err / actual
    scored_at      TIMESTAMPTZ      DEFAULT now(),
    CONSTRAINT load_forecast_scores_pk PRIMARY KEY (ts, iso)
);
CREATE INDEX IF NOT EXISTS lfs_ts ON load_forecast_scores (ts DESC);

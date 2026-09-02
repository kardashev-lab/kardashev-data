# Kardashev Open U.S. Grid Dataset

Documentation for the AWS Open Data Sponsorship Program release.

**Provider:** [Kardashev Labs](https://kardashevlabs.org)  
**Registry:** `registry.opendata.aws/kardashev-open-us-grid-dataset/` (pending launch)  
**S3 bucket:** `s3://kardashev-open-us-grid/` (us-west-2, pending account link)  
**Live API (companion):** https://data.kardashevlabs.org/docs  
**Contact:** ashutosh@kardashevlabs.org

---

## Overview

Harmonized, cloud-optimized U.S. power grid data derived from public ISO, RTO, and federal sources. Kardashev Labs ingests public filings and market data, normalizes schemas, and publishes Parquet partitions with JSON schema sidecars and per-dataset README files.

**v1 open release scope (S3):** ERCOT interconnection GIS film, ERCOT large-load queue observations, derived ERCOT timeline aggregates, and EIA-based reference tables. Additional ISO layers may be added in later releases where redistribution rights are clear.

**Not included in the open S3 release:** bulk republication of ISO datasets whose public terms restrict redistribution (for example PJM Data Miner fields, MISO/SPP website materials). Those sources may still appear in the companion API under source-specific terms; they are excluded from this open dataset until rights are confirmed.

---

## License

**Kardashev-produced files** on S3 (schemas, metadata, normalized Parquet, derived tables, documentation) are licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

Attribution example:

> Kardashev Open U.S. Grid Dataset, Kardashev Labs, accessed [DATE], registry.opendata.aws/kardashev-open-us-grid-dataset/

**Upstream sources** retain their own terms. Each dataset README under `metadata/` documents the source, retrieval method, and redistribution notes. Users are responsible for complying with upstream terms when combining Kardashev derivatives with third-party data.

Open-source ingest and tooling: [kardashev-py](https://github.com/kardashev-lab/kardashev-py) (MIT).

---

## Bucket layout

```
s3://kardashev-open-us-grid/
├── README.txt
├── metadata/
│   ├── schema/
│   │   ├── ercot-gis-snapshots.json
│   │   ├── ercot-gis-timelines.json
│   │   ├── ercot-large-load-observations.json
│   │   └── eia-fuel-mix.json
│   └── sources/
│       ├── ercot-gis.md
│       ├── ercot-large-load.md
│       └── eia.md
└── data/
    ├── parquet/
    │   ├── ercot_gis_snapshots/
    │   │   └── snapshot_month=YYYY-MM/
    │   │       └── part-*.parquet
    │   ├── ercot_gis_timelines/
    │   │   └── computed_at=YYYY-MM-DD/
    │   │       └── part-*.parquet
    │   ├── ercot_large_load_observations/
    │   │   └── snapshot_month=YYYY-MM/
    │   │       └── part-*.parquet
    │   └── eia_fuel_mix/
    │       └── iso=ISO/
    │           └── date=YYYY-MM-DD/
    │               └── part-*.parquet
    └── manifest/
        └── release-YYYYMMDD.json
```

Partitions use Hive-style `key=value` prefixes where natural (month, ISO, date). Files are individual Parquet objects (not tar/zip archives) for Athena, DuckDB, and Polars access.

---

## Datasets

### 1. `ercot_gis_snapshots`

Point-in-time ERCOT generation interconnection queue rows from monthly GIS Report filings (MIS reportTypeId 15933). One row per interconnection project (`queue_id`) per `snapshot_month`.

| Column | Type | Description |
|--------|------|-------------|
| `queue_id` | string | ERCOT INR / queue identifier (source-native) |
| `snapshot_month` | string | Filing month `YYYY-MM` from GIS report filename |
| `project_name` | string | Project name as filed |
| `gim_study_phase` | string | GIM study phase label |
| `county` | string | Texas county |
| `zone` | string | ERCOT load zone (e.g. `LZ_WEST`) |
| `projected_cod` | string | Projected commercial operation date (as filed, text) |
| `fuel` | string | Fuel type |
| `technology` | string | Technology detail |
| `capacity_mw` | float | Nameplate capacity (MW) |
| `screening_study_started` | string | Milestone date as filed |
| `screening_study_complete` | string | Milestone date as filed |
| `ia_signed` | string | Interconnection agreement signed date |
| `construction_start` | string | Construction start date |
| `construction_end` | string | Construction end date |
| `approved_for_energization` | string | Approved for energization date |
| `approved_for_synchronization` | string | Approved for synchronization date |
| `poi_location` | string | Point of interconnection text |
| `fetched_at` | timestamp | Kardashev ingest timestamp (UTC) |

**Source:** ERCOT MIS public GIS reports.  
**Cadence:** Monthly (after ERCOT publishes each GIS report).  
**Upstream terms:** ERCOT public website terms permit use/reproduction/redistribution of publicly available contents; raw data may be used in compilations and analyses. See `metadata/sources/ercot-gis.md`.  
**Tool:** https://interconnection-queue.kardashevlabs.org/interconnection-timelines

---

### 2. `ercot_gis_timelines`

Precomputed duration statistics derived from `ercot_gis_snapshots` (medians/means by zone and fuel). Refreshed after each monthly GIS ingest.

| Column | Type | Description |
|--------|------|-------------|
| `metric` | string | `full_process_days`, `build_phase_days`, `cod_slip_days`, `pending_years_in_queue`, `annual_energized_mw`, etc. |
| `group_type` | string | `zone` or `fuel` |
| `group_value` | string | Zone code or fuel label |
| `sample_count` | int | Projects in sample |
| `median_days` | float | Median duration (days) |
| `mean_days` | float | Mean duration (days) |
| `median_years` | float | Median duration (years), where applicable |
| `total_mw` | float | Pending MW or throughput MW/yr depending on metric |
| `computed_at` | timestamp | Computation time (UTC) |

**License note:** Derived entirely from ERCOT GIS snapshots; CC BY 4.0 on published aggregates.

---

### 3. `ercot_large_load_observations`

Filing observations from ERCOT Large Load Working Group (and predecessor LFLTF) status decks. Each row is one published deck extraction; restatements for the same month are preserved (not overwritten).

| Column | Type | Description |
|--------|------|-------------|
| `source_url` | string | Primary key; ERCOT meeting attachment URL |
| `snapshot_month` | date | Month the chart data point represents |
| `report_date` | date | Meeting / report publish date |
| `total_mw` | float | Total requested large-load capacity (MW) |
| `colocated_mw` | float | Colocated portion (MW) |
| `standalone_mw` | float | Standalone portion (MW) |
| `by_status` | object | Status bucket → MW |
| `by_size_bucket` | object | Size bucket → `{count, mw}` |
| `by_type` | object | Load type → `{pct, mw}` |
| `by_zone` | object | LLWG geography → MW (`lz_west`, `lz_north`, `other`) |
| `approved_to_energize_mw` | float | Cumulative approved-to-energize MW |
| `planning_studies_approved_mw` | float | Cumulative planning studies approved MW |
| `trailing_12mo` | object | Month → MW from deck "Past 12 Months" chart |
| `extracted_at` | timestamp | Extraction time (UTC) |

**Source:** ERCOT LLWG / LFLTF public meeting materials (chart-based PDFs). Values are vision-extracted from published charts; see methodology notes in `metadata/sources/ercot-large-load.md`.  
**Cadence:** Monthly when ERCOT posts a new deck.  
**Tool:** https://large-load-tracker.kardashevlabs.org

---

### 4. `eia_fuel_mix` (v1 EIA layer)

Five-minute generation by fuel type for U.S. ISOs and EIA balancing authorities. Example of the EIA open-data layers included in v1.

| Column | Type | Description |
|--------|------|-------------|
| `ts` | timestamp | Interval start (UTC) |
| `iso` | string | ISO or BA code |
| `fuel_type` | string | Normalized fuel label |
| `mw` | float | Generation (MW) |

**Source:** [EIA Open Data API](https://www.eia.gov/opendata/). U.S. government work; attribution required; do not imply EIA endorsement.  
**Cadence:** Near real-time (5-minute where available).

Additional EIA tables (generation, capacity, retail prices) may be added in later releases using the same schema pattern.

---

## Reading the data

### AWS CLI

```bash
aws s3 ls s3://kardashev-open-us-grid/data/parquet/ercot_gis_snapshots/ --no-sign-request
```

### DuckDB

```sql
INSTALL httpfs;
LOAD httpfs;
SET s3_region = 'us-west-2';

SELECT queue_id, snapshot_month, zone, capacity_mw
FROM read_parquet('s3://kardashev-open-us-grid/data/parquet/ercot_gis_snapshots/**/*.parquet')
WHERE zone = 'LZ_WEST'
LIMIT 10;
```

### Python (PyArrow / Polars)

```python
import polars as pl

df = pl.read_parquet(
    "s3://kardashev-open-us-grid/data/parquet/ercot_gis_timelines/**/*.parquet",
    storage_options={"region": "us-west-2"},
)
```

### Amazon Athena

Create an external table pointing at the Hive partitions under `data/parquet/<dataset>/`. JSON schemas in `metadata/schema/` match Athena column definitions.

---

## Update policy

| Dataset | Typical lag | Notes |
|---------|-------------|-------|
| ERCOT GIS snapshots | ~monthly | After ERCOT posts GIS report |
| ERCOT GIS timelines | ~monthly | Recomputed after GIS ingest |
| ERCOT large load | ~monthly | When LLWG deck is published |
| EIA fuel mix | minutes–hours | Polling EIA API |

Each release writes a `manifest/release-YYYYMMDD.json` listing partitions added or replaced.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-09-02 | Initial documentation draft for AWS onboarding |

---

## Citation

Ashutosh Mathore, Kardashev Labs. *Kardashev Open U.S. Grid Dataset.* Accessed [DATE]. https://registry.opendata.aws/kardashev-open-us-grid-dataset/

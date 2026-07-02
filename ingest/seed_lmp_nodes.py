"""
Seed the lmp_nodes table with node coordinates for each ISO.

Run once (or re-run to refresh):
    python -m ingest.seed_lmp_nodes

Sources:
- NYISO: 11 load zones with well-known centroids
- ISONE: 6 load zones with well-known centroids
- PJM: Major hubs + aggregates (coordinates from PJM public data)
- CAISO: Trading hubs + major nodes (CAISO OASIS)
- MISO: Load resource zones (LRZs 1-10)
- ERCOT: Settlement point hubs
- SPP: North/South hubs + aggregates

MVP: Hub and zone nodes only (~150 total). Full nodal expansion is v2.
"""

from __future__ import annotations

import asyncio
import os
from typing import TypedDict

import asyncpg


class NodeRecord(TypedDict):
    node_id: str
    iso: str
    name: str
    lat: float
    lng: float
    zone: str | None
    voltage_kv: float | None


NODES: list[NodeRecord] = [
    # -------------------------------------------------------------------------
    # NYISO — 11 load zones identified by PTID (numeric IDs used in lmp table)
    # PTIDs from NYISO public data; zones A-K
    # -------------------------------------------------------------------------
    {"node_id": "61752", "iso": "NYISO", "name": "Capital Zone (F)", "lat": 42.652, "lng": -73.756, "zone": "F", "voltage_kv": None},
    {"node_id": "61753", "iso": "NYISO", "name": "Central Zone (C)", "lat": 43.048, "lng": -76.147, "zone": "C", "voltage_kv": None},
    {"node_id": "61754", "iso": "NYISO", "name": "Dunwoodie Zone (I)", "lat": 40.937, "lng": -73.856, "zone": "I", "voltage_kv": None},
    {"node_id": "61755", "iso": "NYISO", "name": "Genesee Zone (B)", "lat": 43.161, "lng": -77.610, "zone": "B", "voltage_kv": None},
    {"node_id": "61756", "iso": "NYISO", "name": "Hudson Valley (G)", "lat": 41.701, "lng": -74.024, "zone": "G", "voltage_kv": None},
    {"node_id": "61757", "iso": "NYISO", "name": "Long Island (K)", "lat": 40.789, "lng": -73.135, "zone": "K", "voltage_kv": None},
    {"node_id": "61758", "iso": "NYISO", "name": "Mohawk Valley (E)", "lat": 43.100, "lng": -75.232, "zone": "E", "voltage_kv": None},
    {"node_id": "61759", "iso": "NYISO", "name": "Millwood Zone (H)", "lat": 41.202, "lng": -73.803, "zone": "H", "voltage_kv": None},
    {"node_id": "61760", "iso": "NYISO", "name": "New York City (J)", "lat": 40.713, "lng": -74.006, "zone": "J", "voltage_kv": None},
    {"node_id": "61761", "iso": "NYISO", "name": "North Zone (D)", "lat": 44.698, "lng": -73.453, "zone": "D", "voltage_kv": None},
    {"node_id": "61762", "iso": "NYISO", "name": "West Zone (A)", "lat": 42.886, "lng": -78.878, "zone": "A", "voltage_kv": None},

    # -------------------------------------------------------------------------
    # ISONE — 6 load zones (CT, ME, NH, NEMA, RI, SEMA, VT, WCMA)
    # -------------------------------------------------------------------------
    {"node_id": ".CT", "iso": "ISONE", "name": "Connecticut", "lat": 41.603, "lng": -72.723, "zone": "CT", "voltage_kv": None},
    {"node_id": ".ME", "iso": "ISONE", "name": "Maine", "lat": 45.253, "lng": -69.445, "zone": "ME", "voltage_kv": None},
    {"node_id": ".NH", "iso": "ISONE", "name": "New Hampshire", "lat": 43.193, "lng": -71.572, "zone": "NH", "voltage_kv": None},
    {"node_id": ".NEMA", "iso": "ISONE", "name": "Northeast Massachusetts", "lat": 42.576, "lng": -71.006, "zone": "NEMA", "voltage_kv": None},
    {"node_id": ".RI", "iso": "ISONE", "name": "Rhode Island", "lat": 41.700, "lng": -71.477, "zone": "RI", "voltage_kv": None},
    {"node_id": ".SEMA", "iso": "ISONE", "name": "Southeast Massachusetts", "lat": 41.902, "lng": -71.024, "zone": "SEMA", "voltage_kv": None},
    {"node_id": ".VT", "iso": "ISONE", "name": "Vermont", "lat": 44.045, "lng": -72.710, "zone": "VT", "voltage_kv": None},
    {"node_id": ".WCMA", "iso": "ISONE", "name": "West/Central Massachusetts", "lat": 42.102, "lng": -72.590, "zone": "WCMA", "voltage_kv": None},

    # -------------------------------------------------------------------------
    # PJM — Major hubs (node_ids are PJM pnode IDs, matching the lmp table)
    # -------------------------------------------------------------------------
    {"node_id": "33092371", "iso": "PJM", "name": "PJM Western Hub", "lat": 40.440, "lng": -79.996, "zone": "AEP", "voltage_kv": 345.0},
    {"node_id": "50969827", "iso": "PJM", "name": "Eastern Hub", "lat": 40.222, "lng": -74.325, "zone": "PPL", "voltage_kv": 345.0},
    {"node_id": "34508503", "iso": "PJM", "name": "AEP-Dayton Hub", "lat": 39.961, "lng": -83.003, "zone": "AEP", "voltage_kv": 345.0},
    {"node_id": "33092396", "iso": "PJM", "name": "ComEd Hub (Chicago)", "lat": 41.833, "lng": -87.832, "zone": "COMED", "voltage_kv": 345.0},

    # -------------------------------------------------------------------------
    # CAISO — Trading hubs and major APNodes
    # -------------------------------------------------------------------------
    {"node_id": "TH_NP15_GEN-APND", "iso": "CAISO", "name": "NP15 Trading Hub (North)", "lat": 38.291, "lng": -121.500, "zone": "NP15", "voltage_kv": 500.0},
    {"node_id": "TH_SP15_GEN-APND", "iso": "CAISO", "name": "SP15 Trading Hub (South)", "lat": 34.052, "lng": -118.244, "zone": "SP15", "voltage_kv": 500.0},
    {"node_id": "TH_ZP26_GEN-APND", "iso": "CAISO", "name": "ZP26 Trading Hub (Central)", "lat": 36.778, "lng": -119.418, "zone": "ZP26", "voltage_kv": 500.0},
    {"node_id": "PGAE_APND", "iso": "CAISO", "name": "PG&E Aggregate", "lat": 37.814, "lng": -122.268, "zone": "NP15", "voltage_kv": None},
    {"node_id": "SCE_APND", "iso": "CAISO", "name": "SCE Aggregate", "lat": 34.052, "lng": -118.244, "zone": "SP15", "voltage_kv": None},
    {"node_id": "SDGE_APND", "iso": "CAISO", "name": "SDG&E Aggregate", "lat": 32.715, "lng": -117.157, "zone": "SP15", "voltage_kv": None},
    {"node_id": "SMUD_APND", "iso": "CAISO", "name": "SMUD Aggregate (Sacramento)", "lat": 38.581, "lng": -121.494, "zone": "NP15", "voltage_kv": None},
    {"node_id": "NEVP_APND", "iso": "CAISO", "name": "NV Energy Aggregate", "lat": 36.174, "lng": -115.137, "zone": "NP15", "voltage_kv": None},
    {"node_id": "TIDC_APND", "iso": "CAISO", "name": "Turlock Irrigation District", "lat": 37.504, "lng": -120.850, "zone": "NP15", "voltage_kv": None},

    # -------------------------------------------------------------------------
    # MISO — Hub nodes (actual node_ids used in lmp table)
    # -------------------------------------------------------------------------
    {"node_id": "ARKANSAS.HUB", "iso": "MISO", "name": "Arkansas Hub", "lat": 34.746, "lng": -92.289, "zone": "ARKANSAS", "voltage_kv": None},
    {"node_id": "ILLINOIS.HUB", "iso": "MISO", "name": "Illinois Hub", "lat": 40.633, "lng": -89.399, "zone": "ILLINOIS", "voltage_kv": None},
    {"node_id": "INDIANA.HUB", "iso": "MISO", "name": "Indiana Hub", "lat": 39.769, "lng": -86.158, "zone": "INDIANA", "voltage_kv": None},
    {"node_id": "LOUISIANA.HUB", "iso": "MISO", "name": "Louisiana Hub", "lat": 30.457, "lng": -91.187, "zone": "LOUISIANA", "voltage_kv": None},
    {"node_id": "MICHIGAN.HUB", "iso": "MISO", "name": "Michigan Hub", "lat": 42.733, "lng": -84.555, "zone": "MICHIGAN", "voltage_kv": None},
    {"node_id": "MINN.HUB", "iso": "MISO", "name": "Minnesota Hub", "lat": 44.978, "lng": -93.265, "zone": "MINNESOTA", "voltage_kv": None},
    {"node_id": "MS.HUB", "iso": "MISO", "name": "Mississippi Hub", "lat": 32.298, "lng": -90.184, "zone": "MISSISSIPPI", "voltage_kv": None},
    {"node_id": "TEXAS.HUB", "iso": "MISO", "name": "Texas Hub (MISO South)", "lat": 32.800, "lng": -96.800, "zone": "TEXAS", "voltage_kv": None},

    # -------------------------------------------------------------------------
    # ERCOT — Settlement point hubs (actual node_ids from lmp table)
    # -------------------------------------------------------------------------
    {"node_id": "HB_BUSAVG", "iso": "ERCOT", "name": "ERCOT Bus Average Hub", "lat": 31.000, "lng": -100.000, "zone": "HUB", "voltage_kv": None},
    {"node_id": "HB_HOUSTON", "iso": "ERCOT", "name": "Houston Hub", "lat": 29.760, "lng": -95.369, "zone": "HOUSTON", "voltage_kv": 345.0},
    {"node_id": "HB_HUBAVG", "iso": "ERCOT", "name": "ERCOT Hub Average", "lat": 31.000, "lng": -99.000, "zone": "HUB", "voltage_kv": None},
    {"node_id": "HB_NORTH", "iso": "ERCOT", "name": "North Hub (Dallas/Fort Worth)", "lat": 32.783, "lng": -97.350, "zone": "NORTH", "voltage_kv": 345.0},
    {"node_id": "HB_PAN", "iso": "ERCOT", "name": "Panhandle Hub (West Texas Wind)", "lat": 35.207, "lng": -101.835, "zone": "PAN", "voltage_kv": 345.0},
    {"node_id": "HB_SOUTH", "iso": "ERCOT", "name": "South Hub (San Antonio)", "lat": 29.425, "lng": -98.494, "zone": "SOUTH", "voltage_kv": 345.0},
    {"node_id": "HB_WEST", "iso": "ERCOT", "name": "West Hub (Permian Basin)", "lat": 31.849, "lng": -102.367, "zone": "WEST", "voltage_kv": 345.0},
    # Load zones
    {"node_id": "LZ_AEN", "iso": "ERCOT", "name": "AEN Load Zone (South Texas)", "lat": 27.800, "lng": -97.396, "zone": "AEN", "voltage_kv": None},
    {"node_id": "LZ_CPS", "iso": "ERCOT", "name": "CPS Load Zone (San Antonio)", "lat": 29.425, "lng": -98.494, "zone": "CPS", "voltage_kv": None},
    {"node_id": "LZ_HOUSTON", "iso": "ERCOT", "name": "Houston Load Zone", "lat": 29.760, "lng": -95.369, "zone": "HOUSTON", "voltage_kv": None},
    {"node_id": "LZ_LCRA", "iso": "ERCOT", "name": "LCRA Load Zone (Central TX)", "lat": 30.267, "lng": -97.743, "zone": "LCRA", "voltage_kv": None},
    {"node_id": "LZ_NORTH", "iso": "ERCOT", "name": "North Load Zone (DFW)", "lat": 32.783, "lng": -97.350, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "LZ_RAYBN", "iso": "ERCOT", "name": "Rayburn Load Zone (East TX)", "lat": 30.565, "lng": -96.300, "zone": "RAYBN", "voltage_kv": None},
    {"node_id": "LZ_SOUTH", "iso": "ERCOT", "name": "South Load Zone", "lat": 28.696, "lng": -100.480, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "LZ_WEST", "iso": "ERCOT", "name": "West Load Zone (Permian)", "lat": 31.849, "lng": -102.367, "zone": "WEST", "voltage_kv": None},

    # -------------------------------------------------------------------------
    # SPP — Hubs and aggregates (actual node_ids from lmp table)
    # -------------------------------------------------------------------------
    {"node_id": "SPPNORTH_HUB", "iso": "SPP", "name": "SPP North Hub", "lat": 41.257, "lng": -96.344, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "SPPSOUTH_HUB", "iso": "SPP", "name": "SPP South Hub", "lat": 35.467, "lng": -97.517, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "CSWS_HUB", "iso": "SPP", "name": "AEP-SWEPCO Hub (OK/TX/AR)", "lat": 35.467, "lng": -97.517, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "GRDA_HUB", "iso": "SPP", "name": "Grand River Dam Authority Hub (OK)", "lat": 36.476, "lng": -94.880, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "INDN_INDN", "iso": "SPP", "name": "Indiana Michigan Power", "lat": 41.682, "lng": -86.251, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "KCPLHUB", "iso": "SPP", "name": "Kansas City Power & Light Hub (MO/KS)", "lat": 39.099, "lng": -94.578, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "NPPD_NPPD", "iso": "SPP", "name": "Nebraska Public Power District", "lat": 40.797, "lng": -100.792, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "OKGE_OKGE", "iso": "SPP", "name": "Oklahoma Gas & Electric", "lat": 35.467, "lng": -97.517, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "OPPD_OPPD", "iso": "SPP", "name": "Omaha Public Power District (NE)", "lat": 41.257, "lng": -95.956, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "SECI_HUB", "iso": "SPP", "name": "Sunflower Electric Hub (KS)", "lat": 37.694, "lng": -97.314, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "SPRM_SPRM", "iso": "SPP", "name": "Empire District Electric (MO)", "lat": 37.082, "lng": -94.514, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "SPS_SPS", "iso": "SPP", "name": "Southwestern Public Service (TX/NM panhandle)", "lat": 33.590, "lng": -101.855, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "WR_WR", "iso": "SPP", "name": "Evergy Kansas (formerly Westar)", "lat": 39.056, "lng": -95.689, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "WFEC_WFEC", "iso": "SPP", "name": "Western Farmers Electric Coop (OK)", "lat": 35.225, "lng": -99.000, "zone": "SOUTH", "voltage_kv": None},
]


async def seed(database_url: str) -> None:
    conn = await asyncpg.connect(database_url)
    try:
        await conn.executemany(
            """
            INSERT INTO lmp_nodes (node_id, iso, name, lat, lng, zone, voltage_kv)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (node_id, iso) DO UPDATE SET
                name       = EXCLUDED.name,
                lat        = EXCLUDED.lat,
                lng        = EXCLUDED.lng,
                zone       = EXCLUDED.zone,
                voltage_kv = EXCLUDED.voltage_kv
            """,
            [
                (
                    n["node_id"], n["iso"], n["name"],
                    n["lat"], n["lng"], n.get("zone"), n.get("voltage_kv"),
                )
                for n in NODES
            ],
        )
        print(f"Seeded {len(NODES)} nodes across {len({n['iso'] for n in NODES})} ISOs.")
    finally:
        await conn.close()


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    asyncio.run(seed(url))

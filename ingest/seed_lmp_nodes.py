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
    # NYISO — 11 load zones (A through K)
    # -------------------------------------------------------------------------
    {"node_id": "CAPITL", "iso": "NYISO", "name": "Capital Zone (F)", "lat": 42.652, "lng": -73.756, "zone": "F", "voltage_kv": None},
    {"node_id": "CENTRL", "iso": "NYISO", "name": "Central Zone (C)", "lat": 43.048, "lng": -76.147, "zone": "C", "voltage_kv": None},
    {"node_id": "DUNWOD", "iso": "NYISO", "name": "Dunwoodie (H)", "lat": 40.937, "lng": -73.856, "zone": "H", "voltage_kv": None},
    {"node_id": "GENESE", "iso": "NYISO", "name": "Genesee Zone (B)", "lat": 43.161, "lng": -77.610, "zone": "B", "voltage_kv": None},
    {"node_id": "HUD VL", "iso": "NYISO", "name": "Hudson Valley (G)", "lat": 41.701, "lng": -74.024, "zone": "G", "voltage_kv": None},
    {"node_id": "LONGIL", "iso": "NYISO", "name": "Long Island (K)", "lat": 40.789, "lng": -73.135, "zone": "K", "voltage_kv": None},
    {"node_id": "MHK VL", "iso": "NYISO", "name": "Mohawk Valley (E)", "lat": 43.100, "lng": -75.232, "zone": "E", "voltage_kv": None},
    {"node_id": "MILLWD", "iso": "NYISO", "name": "Millwood (I)", "lat": 41.202, "lng": -73.803, "zone": "I", "voltage_kv": None},
    {"node_id": "N.Y.C.", "iso": "NYISO", "name": "New York City (J)", "lat": 40.713, "lng": -74.006, "zone": "J", "voltage_kv": None},
    {"node_id": "NORTH", "iso": "NYISO", "name": "North Zone (D)", "lat": 44.698, "lng": -73.453, "zone": "D", "voltage_kv": None},
    {"node_id": "WEST", "iso": "NYISO", "name": "West Zone (A)", "lat": 42.886, "lng": -78.878, "zone": "A", "voltage_kv": None},

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
    # PJM — Major hubs and aggregates
    # -------------------------------------------------------------------------
    {"node_id": "AEP-DAYTON HUB", "iso": "PJM", "name": "AEP-Dayton Hub", "lat": 39.961, "lng": -83.003, "zone": "AEP", "voltage_kv": 345.0},
    {"node_id": "AEP GEN HUB", "iso": "PJM", "name": "AEP Generation Hub", "lat": 38.887, "lng": -82.033, "zone": "AEP", "voltage_kv": 345.0},
    {"node_id": "ATSI GEN HUB", "iso": "PJM", "name": "ATSI Generation Hub", "lat": 41.499, "lng": -81.695, "zone": "ATSI", "voltage_kv": 345.0},
    {"node_id": "COMED HUB", "iso": "PJM", "name": "ComEd Hub (Chicago)", "lat": 41.833, "lng": -87.832, "zone": "COMED", "voltage_kv": 345.0},
    {"node_id": "DOMINION HUB", "iso": "PJM", "name": "Dominion Hub (Virginia)", "lat": 37.431, "lng": -78.656, "zone": "DOM", "voltage_kv": 500.0},
    {"node_id": "EASTERN HUB", "iso": "PJM", "name": "Eastern Hub", "lat": 40.440, "lng": -79.996, "zone": "PPL", "voltage_kv": 345.0},
    {"node_id": "ILLINOIS HUB", "iso": "PJM", "name": "Illinois Hub", "lat": 40.633, "lng": -89.399, "zone": "AMIL", "voltage_kv": None},
    {"node_id": "INDIANA HUB", "iso": "PJM", "name": "Indiana Hub", "lat": 39.769, "lng": -86.158, "zone": "AEP", "voltage_kv": None},
    {"node_id": "JCPL ZONE", "iso": "PJM", "name": "Jersey Central Power & Light Zone", "lat": 40.222, "lng": -74.325, "zone": "JCPL", "voltage_kv": 230.0},
    {"node_id": "METED ZONE", "iso": "PJM", "name": "Met-Ed Zone (PA)", "lat": 40.335, "lng": -76.418, "zone": "METED", "voltage_kv": None},
    {"node_id": "NI HUB", "iso": "PJM", "name": "Northern Illinois Hub", "lat": 41.892, "lng": -87.632, "zone": "COMED", "voltage_kv": 345.0},
    {"node_id": "OHIO HUB", "iso": "PJM", "name": "Ohio Hub", "lat": 40.417, "lng": -82.907, "zone": "AEP", "voltage_kv": None},
    {"node_id": "PEPCO ZONE", "iso": "PJM", "name": "Potomac Electric Zone (DC/MD)", "lat": 38.907, "lng": -77.037, "zone": "PEPCO", "voltage_kv": 230.0},
    {"node_id": "PJMW HUB", "iso": "PJM", "name": "PJM Western Hub", "lat": 40.440, "lng": -79.996, "zone": "AEP", "voltage_kv": 345.0},
    {"node_id": "PPL ZONE", "iso": "PJM", "name": "PPL Zone (PA)", "lat": 40.602, "lng": -75.490, "zone": "PPL", "voltage_kv": 230.0},
    {"node_id": "PSEG ZONE", "iso": "PJM", "name": "PSEG Zone (NJ)", "lat": 40.692, "lng": -74.044, "zone": "PSEG", "voltage_kv": 230.0},
    {"node_id": "RECO ZONE", "iso": "PJM", "name": "Rockland Electric Zone (NY border)", "lat": 41.148, "lng": -74.159, "zone": "RECO", "voltage_kv": None},
    {"node_id": "UGI ZONE", "iso": "PJM", "name": "UGI Zone (PA)", "lat": 40.243, "lng": -76.929, "zone": "UGI", "voltage_kv": None},

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
    # MISO — Load resource zones (LRZ 1–10)
    # -------------------------------------------------------------------------
    {"node_id": "LRZ1", "iso": "MISO", "name": "LRZ 1 (Manitoba/Upper Midwest)", "lat": 46.879, "lng": -96.789, "zone": "LRZ1", "voltage_kv": None},
    {"node_id": "LRZ2", "iso": "MISO", "name": "LRZ 2 (Minnesota/Wisconsin)", "lat": 44.978, "lng": -93.265, "zone": "LRZ2", "voltage_kv": None},
    {"node_id": "LRZ3", "iso": "MISO", "name": "LRZ 3 (Michigan UP)", "lat": 46.516, "lng": -84.335, "zone": "LRZ3", "voltage_kv": None},
    {"node_id": "LRZ4", "iso": "MISO", "name": "LRZ 4 (Michigan LP)", "lat": 43.453, "lng": -84.953, "zone": "LRZ4", "voltage_kv": None},
    {"node_id": "LRZ5", "iso": "MISO", "name": "LRZ 5 (Illinois/Iowa)", "lat": 41.838, "lng": -88.010, "zone": "LRZ5", "voltage_kv": None},
    {"node_id": "LRZ6", "iso": "MISO", "name": "LRZ 6 (Indiana/Ohio)", "lat": 39.769, "lng": -86.158, "zone": "LRZ6", "voltage_kv": None},
    {"node_id": "LRZ7", "iso": "MISO", "name": "LRZ 7 (Missouri/Kansas)", "lat": 38.573, "lng": -92.174, "zone": "LRZ7", "voltage_kv": None},
    {"node_id": "LRZ8", "iso": "MISO", "name": "LRZ 8 (Arkansas/Mississippi)", "lat": 34.746, "lng": -92.289, "zone": "LRZ8", "voltage_kv": None},
    {"node_id": "LRZ9", "iso": "MISO", "name": "LRZ 9 (Louisiana)", "lat": 30.457, "lng": -91.187, "zone": "LRZ9", "voltage_kv": None},
    {"node_id": "LRZ10", "iso": "MISO", "name": "LRZ 10 (Texas Panhandle)", "lat": 35.207, "lng": -101.835, "zone": "LRZ10", "voltage_kv": None},

    # -------------------------------------------------------------------------
    # ERCOT — Settlement point hubs and load zones
    # -------------------------------------------------------------------------
    {"node_id": "HB_BUSAVG", "iso": "ERCOT", "name": "ERCOT Bus Average Hub", "lat": 31.000, "lng": -100.000, "zone": "HUB", "voltage_kv": None},
    {"node_id": "HB_HOUSTON", "iso": "ERCOT", "name": "Houston Hub", "lat": 29.760, "lng": -95.369, "zone": "HOUSTON", "voltage_kv": 345.0},
    {"node_id": "HB_NORTH", "iso": "ERCOT", "name": "North Hub (Dallas/Fort Worth)", "lat": 32.783, "lng": -97.350, "zone": "NORTH", "voltage_kv": 345.0},
    {"node_id": "HB_PAN", "iso": "ERCOT", "name": "Panhandle Hub (West Texas Wind)", "lat": 35.207, "lng": -101.835, "zone": "PAN", "voltage_kv": 345.0},
    {"node_id": "HB_SOUTH", "iso": "ERCOT", "name": "South Hub (San Antonio)", "lat": 29.425, "lng": -98.494, "zone": "SOUTH", "voltage_kv": 345.0},
    {"node_id": "HB_WEST", "iso": "ERCOT", "name": "West Hub (Permian Basin)", "lat": 31.849, "lng": -102.367, "zone": "WEST", "voltage_kv": 345.0},
    {"node_id": "LZ_AEN", "iso": "ERCOT", "name": "AEN Load Zone (South Texas)", "lat": 27.800, "lng": -97.396, "zone": "AEN", "voltage_kv": None},
    {"node_id": "LZ_CPS", "iso": "ERCOT", "name": "CPS Load Zone (San Antonio)", "lat": 29.425, "lng": -98.494, "zone": "CPS", "voltage_kv": None},
    {"node_id": "LZ_HOUSTON", "iso": "ERCOT", "name": "Houston Load Zone", "lat": 29.760, "lng": -95.369, "zone": "HOUSTON", "voltage_kv": None},
    {"node_id": "LZ_LCRA", "iso": "ERCOT", "name": "LCRA Load Zone (Central TX)", "lat": 30.267, "lng": -97.743, "zone": "LCRA", "voltage_kv": None},
    {"node_id": "LZ_NORTH", "iso": "ERCOT", "name": "North Load Zone (DFW)", "lat": 32.783, "lng": -97.350, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "LZ_RAYBN", "iso": "ERCOT", "name": "Rayburn Load Zone (East TX)", "lat": 30.565, "lng": -96.300, "zone": "RAYBN", "voltage_kv": None},
    {"node_id": "LZ_SOUTH", "iso": "ERCOT", "name": "South Load Zone", "lat": 28.696, "lng": -100.480, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "LZ_WEST", "iso": "ERCOT", "name": "West Load Zone (Permian)", "lat": 31.849, "lng": -102.367, "zone": "WEST", "voltage_kv": None},

    # -------------------------------------------------------------------------
    # SPP — North/South hubs and aggregates
    # -------------------------------------------------------------------------
    {"node_id": "SPP_NORTH_HUB", "iso": "SPP", "name": "SPP North Hub", "lat": 41.257, "lng": -96.344, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "SPP_SOUTH_HUB", "iso": "SPP", "name": "SPP South Hub", "lat": 35.467, "lng": -97.517, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "CSWS", "iso": "SPP", "name": "Central & South West Services (OK)", "lat": 35.467, "lng": -97.517, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "GRDA", "iso": "SPP", "name": "Grand River Dam Authority (OK)", "lat": 36.476, "lng": -94.880, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "INDN", "iso": "SPP", "name": "Indiana Michigan Power (IN)", "lat": 41.682, "lng": -86.251, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "KCPL", "iso": "SPP", "name": "Kansas City Power & Light (MO/KS)", "lat": 39.099, "lng": -94.578, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "NPPD", "iso": "SPP", "name": "Nebraska Public Power District", "lat": 40.797, "lng": -100.792, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "OKGE", "iso": "SPP", "name": "Oklahoma Gas & Electric", "lat": 35.467, "lng": -97.517, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "OPPD", "iso": "SPP", "name": "Omaha Public Power District (NE)", "lat": 41.257, "lng": -95.956, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "SECI", "iso": "SPP", "name": "Sunflower Electric (KS)", "lat": 37.694, "lng": -97.314, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "SPRM", "iso": "SPP", "name": "Empire District Electric (MO)", "lat": 37.082, "lng": -94.514, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "SPS", "iso": "SPP", "name": "Southwestern Public Service (TX panhandle)", "lat": 33.590, "lng": -101.855, "zone": "SOUTH", "voltage_kv": None},
    {"node_id": "WR", "iso": "SPP", "name": "Westar Energy (KS)", "lat": 39.056, "lng": -95.689, "zone": "NORTH", "voltage_kv": None},
    {"node_id": "WFEC", "iso": "SPP", "name": "Western Farmers Electric Coop (OK)", "lat": 35.225, "lng": -99.000, "zone": "SOUTH", "voltage_kv": None},
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

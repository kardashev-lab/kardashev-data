"""
Auto-seed lmp_nodes for nodes that appear in the lmp table but have no coordinates.

Runs after each ingest cycle. Uses pattern-matching for known node types:
- ERCOT: HB_* hubs and LZ_* load zones have fixed geographic centroids
- CAISO: *_APND nodes map to known utility service territories
- Others: skipped (requires manual coord entry or geocoding)

Run:  python -m ingest.seed_lmp_nodes_auto
"""
from __future__ import annotations

import asyncio
import os

import asyncpg

# Known coordinates for node ID patterns
# (node_id, iso) -> (name, lat, lng, zone)
_KNOWN: dict[tuple[str, str], tuple[str, float, float, str | None]] = {
    # ERCOT hubs
    ("HB_BUSAVG",  "ERCOT"): ("ERCOT Bus Average",         31.000, -100.000, "HUB"),
    ("HB_HOUSTON", "ERCOT"): ("Houston Hub",                29.760,  -95.369, "HOUSTON"),
    ("HB_HUBAVG",  "ERCOT"): ("ERCOT Hub Average",         31.000,  -99.000, "HUB"),
    ("HB_NORTH",   "ERCOT"): ("North Hub (DFW)",           32.783,  -97.350, "NORTH"),
    ("HB_PAN",     "ERCOT"): ("Panhandle Hub",             35.207, -101.835, "PAN"),
    ("HB_SOUTH",   "ERCOT"): ("South Hub (San Antonio)",   29.425,  -98.494, "SOUTH"),
    ("HB_WEST",    "ERCOT"): ("West Hub (Permian Basin)",  31.849, -102.367, "WEST"),
    # ERCOT load zones
    ("LZ_AEN",     "ERCOT"): ("AEN Load Zone",             27.800,  -97.396, "AEN"),
    ("LZ_CPS",     "ERCOT"): ("CPS Load Zone (San Antonio)",29.425, -98.494, "CPS"),
    ("LZ_HOUSTON", "ERCOT"): ("Houston Load Zone",         29.760,  -95.369, "HOUSTON"),
    ("LZ_LCRA",    "ERCOT"): ("LCRA Load Zone (Central TX)",30.267, -97.743, "LCRA"),
    ("LZ_NORTH",   "ERCOT"): ("North Load Zone (DFW)",     32.783,  -97.350, "NORTH"),
    ("LZ_RAYBN",   "ERCOT"): ("Rayburn Load Zone (East TX)",30.565, -96.300, "RAYBN"),
    ("LZ_SOUTH",   "ERCOT"): ("South Load Zone",           28.696, -100.480, "SOUTH"),
    ("LZ_WEST",    "ERCOT"): ("West Load Zone (Permian)",  31.849, -102.367, "WEST"),
    # CAISO trading hubs
    ("TH_NP15_GEN-APND", "CAISO"): ("NP15 Trading Hub (North CA)", 38.291, -121.500, "NP15"),
    ("TH_SP15_GEN-APND", "CAISO"): ("SP15 Trading Hub (South CA)", 34.052, -118.244, "SP15"),
    ("TH_ZP26_GEN-APND", "CAISO"): ("ZP26 Trading Hub (Central CA)", 36.778, -119.418, "ZP26"),
    # CAISO LAPs / APNDs (utility service territory centroids)
    ("PGAE_APND",  "CAISO"): ("PG&E Aggregated Pricing Node",     37.814, -122.268, "NP15"),
    ("SCE_APND",   "CAISO"): ("SCE Aggregated Pricing Node",      34.052, -118.244, "SP15"),
    ("SDGE_APND",  "CAISO"): ("SDG&E Aggregated Pricing Node",    32.715, -117.157, "SP15"),
    ("SMUD_APND",  "CAISO"): ("SMUD Aggregated Pricing Node",     38.581, -121.494, "NP15"),
    ("IID_APND",   "CAISO"): ("IID Aggregated Pricing Node",      33.120, -115.560, "SP15"),
    ("VEA_APND",   "CAISO"): ("Valley Electric Aggregated Node",  36.210, -115.980, "NP15"),
    ("TIDC_APND",  "CAISO"): ("Turlock Irrigation District APND", 37.504, -120.850, "NP15"),
    ("BANC_APND",  "CAISO"): ("BANC Aggregated Pricing Node",     38.600, -121.400, "NP15"),
    ("LDWP_APND",  "CAISO"): ("LADWP Aggregated Pricing Node",    34.052, -118.244, "SP15"),
}


async def auto_seed(database_url: str) -> None:
    conn = await asyncpg.connect(database_url)
    try:
        # Find node_ids in lmp that have no lmp_nodes entry
        missing = await conn.fetch("""
            SELECT DISTINCT l.node_id, l.iso
            FROM lmp l
            LEFT JOIN lmp_nodes n ON n.node_id = l.node_id AND n.iso = l.iso
            WHERE n.node_id IS NULL
              AND l.ts >= now() - interval '24 hours'
        """)

        seeded = 0
        for row in missing:
            key = (row["node_id"], row["iso"])
            if key not in _KNOWN:
                continue
            name, lat, lng, zone = _KNOWN[key]
            await conn.execute("""
                INSERT INTO lmp_nodes (node_id, iso, name, lat, lng, zone)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (node_id, iso) DO NOTHING
            """, row["node_id"], row["iso"], name, lat, lng, zone)
            seeded += 1

        skipped = len(missing) - seeded
        print(f"Auto-seeded {seeded} new nodes. {skipped} nodes skipped (no known coords).")
        if skipped > 0:
            unknown = [(r["node_id"], r["iso"]) for r in missing
                       if (r["node_id"], r["iso"]) not in _KNOWN][:10]
            print("Sample unknown nodes:", unknown)
    finally:
        await conn.close()


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    asyncio.run(auto_seed(url))

"""
Seed lmp_nodes for CAISO bus-level pricing nodes via CAISO OASIS ATL_PNODE_MAP.

CAISO does not publish exact substation coordinates. Nodes are placed
deterministically within their zone bounding box (NP15/SP15/ZP26/PACE/PACW)
using an MD5 hash of the node_id for consistent positioning.

Run:  railway run python -m ingest.seed_caiso_pnodes
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta

import asyncpg
import requests

log = logging.getLogger(__name__)

_NS = "http://www.caiso.com/soa/OASISMaster_v1.xsd"

# Zone → (lat_min, lat_max, lng_min, lng_max), display_zone_name
_ZONE_BOXES: dict[str, tuple[tuple[float, float], tuple[float, float], str]] = {
    "TH_NP15_GEN-APND": ((36.5, 41.0), (-124.0, -120.0), "NP15"),
    "TH_SP15_GEN-APND": ((32.5, 35.5), (-121.0, -114.5), "SP15"),
    "TH_ZP26_GEN-APND": ((35.0, 37.5), (-121.5, -117.5), "ZP26"),
    "TH_PACE_GEN-APND": ((37.0, 48.0), (-116.0, -104.0), "PACE"),
    "TH_PACW_GEN-APND": ((42.0, 49.0), (-124.0, -113.0), "PACW"),
}


def _approx_coords(node_id: str, apnode: str) -> tuple[float, float]:
    """Deterministic placement within zone bounding box via MD5 hash."""
    h = int(hashlib.md5(node_id.encode()).hexdigest(), 16)
    t_lat = (h & 0xFFFF) / 0xFFFF
    t_lng = ((h >> 16) & 0xFFFF) / 0xFFFF
    (lat_min, lat_max), (lng_min, lng_max), _ = _ZONE_BOXES.get(
        apnode,
        ((36.0, 42.0), (-124.0, -117.0), "NP15"),
    )
    lat = round(lat_min + t_lat * (lat_max - lat_min), 6)
    lng = round(lng_min + t_lng * (lng_max - lng_min), 6)
    return lat, lng


def _fetch_pnode_map() -> dict[str, str]:
    """Return {pnode_name: apnode_name} for all active CAISO pricing nodes."""
    end = date.today()
    start = end - timedelta(days=7)
    url = (
        "https://oasis.caiso.com/oasisapi/SingleZip"
        f"?queryname=ATL_PNODE_MAP&version=1"
        f"&startdatetime={start.strftime('%Y%m%d')}T00:00-0000"
        f"&enddatetime={end.strftime('%Y%m%d')}T00:00-0000"
    )
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])

    root = ET.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for item in root.findall(f".//{{{_NS}}}ATLS_DATA"):
        apnode = item.findtext(f"{{{_NS}}}APNODE_NAME") or ""
        pnode = item.findtext(f"{{{_NS}}}PNODE_NAME") or ""
        if pnode and apnode and apnode in _ZONE_BOXES:
            mapping[pnode] = apnode
    return mapping


async def seed_caiso_pnodes(database_url: str) -> None:
    print("Fetching CAISO ATL_PNODE_MAP...")
    pnode_map = _fetch_pnode_map()
    print(f"  {len(pnode_map)} bus nodes across {len(set(pnode_map.values()))} zones")

    conn = await asyncpg.connect(database_url)
    try:
        # Skip nodes already in lmp_nodes (don't overwrite exact coords with approx)
        existing = {
            row["node_id"]
            for row in await conn.fetch(
                "SELECT node_id FROM lmp_nodes WHERE iso = 'CAISO'"
            )
        }
        rows = [
            (pnode, "CAISO", pnode, *_approx_coords(pnode, apnode), _ZONE_BOXES[apnode][2])
            for pnode, apnode in pnode_map.items()
            if pnode not in existing
        ]
        if rows:
            await conn.executemany(
                """
                INSERT INTO lmp_nodes (node_id, iso, name, lat, lng, zone)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (node_id, iso) DO NOTHING
                """,
                rows,
            )
        print(f"Seeded {len(rows)} new CAISO nodes ({len(existing)} already existed).")
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    asyncio.run(seed_caiso_pnodes(url))

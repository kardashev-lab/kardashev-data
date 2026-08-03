"""Build county-level HIFLD transmission-line density proxy for Site Clearance C0.

Downloads public HIFLD Electric Power Transmission Lines (ArcGIS FeatureServer),
clips to Texas counties, and writes a small JSON artifact consumed at score time.

  python -m ingest.build_tx_county_wire_proxy
  python -m ingest.build_tx_county_wire_proxy --dry-run  # first page only

Output: data/tx_county_wire_proxy.json (committed; rebuild when HIFLD snapshot ages).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from shapely.geometry import LineString, MultiLineString, shape
from shapely.prepared import prep
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
COUNTIES_PATH = ROOT / "data" / "tx_counties.geojson"
OUT_PATH = ROOT / "data" / "tx_county_wire_proxy.json"

HIFLD_QUERY = (
    "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
    "US_Electric_Power_Transmission_Lines/FeatureServer/0/query"
)
# Texas bbox with a small pad (includes some NM/OK/LA/MX spill — clipped by county).
TX_BBOX = {"xmin": -106.7, "ymin": 25.8, "xmax": -93.4, "ymax": 36.6}
PAGE = 2000
HV_KV = 230.0


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def line_length_km(geom) -> float:
    if geom is None or geom.is_empty:
        return 0.0
    if isinstance(geom, MultiLineString):
        return sum(line_length_km(g) for g in geom.geoms)
    if not isinstance(geom, LineString):
        # ArcGIS sometimes returns MultiLineString via shape(); else skip.
        try:
            coords = list(geom.coords)
        except Exception:
            return 0.0
        total = 0.0
        for i in range(len(coords) - 1):
            total += _haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        return total
    coords = list(geom.coords)
    total = 0.0
    for i in range(len(coords) - 1):
        total += _haversine_km(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
    return total


def county_area_km2(geom) -> float:
    """Rough equal-area from WGS84 centroid (good enough for relative density)."""
    c = geom.centroid
    lat = math.radians(c.y)
    m_per_deg_lat = 111_132.92
    m_per_deg_lon = 111_412.84 * math.cos(lat)
    # geom.area is in deg²
    return abs(geom.area) * m_per_deg_lat * m_per_deg_lon / 1e6


def _fetch_page(offset: int, record_count: int) -> dict[str, Any]:
    geom = {
        **TX_BBOX,
        "spatialReference": {"wkid": 4326},
    }
    params = {
        "where": "1=1",
        "geometry": json.dumps(geom, separators=(",", ":")),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "VOLTAGE,VOLT_CLASS,STATUS,TYPE",
        "returnGeometry": "true",
        "outSR": "4326",
        "resultOffset": str(offset),
        "resultRecordCount": str(record_count),
        "f": "geojson",
    }
    url = f"{HIFLD_QUERY}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "kardashev-labs-wire-proxy/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_all_lines(*, dry_run: bool) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = _fetch_page(offset, 50 if dry_run else PAGE)
        batch = page.get("features") or []
        features.extend(batch)
        print(f"  fetched {len(features)} lines (offset={offset})", flush=True)
        if dry_run or len(batch) < PAGE:
            break
        offset += PAGE
    return features


def load_counties() -> list[dict[str, Any]]:
    raw = json.loads(COUNTIES_PATH.read_text())
    out = []
    for feat in raw["features"]:
        geom = shape(feat["geometry"])
        if geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        name = str(feat["properties"]["name"]).strip()
        out.append(
            {
                "name": name,
                "geoid": feat["properties"].get("geoid"),
                "geometry": geom,
                "area_km2": county_area_km2(geom),
            }
        )
    return out


def build(dry_run: bool = False) -> dict[str, Any]:
    print("Loading Texas counties…", flush=True)
    counties = load_counties()
    geoms = [c["geometry"] for c in counties]
    tree = STRtree(geoms)
    prepared = [prep(g) for g in geoms]

    print("Downloading HIFLD transmission lines (TX bbox)…", flush=True)
    features = fetch_all_lines(dry_run=dry_run)

    # Accumulators per county index
    line_km = defaultdict(float)
    hv_km = defaultdict(float)
    segments = defaultdict(int)

    for feat in features:
        props = feat.get("properties") or {}
        status = str(props.get("STATUS") or "").upper()
        if status and status not in {"IN SERVICE", "IN SERVICE; UNDER CONSTRUCTION", ""}:
            # Keep IN SERVICE; skip abandoned/proposed when labeled.
            if "ABANDON" in status or "PROPOSED" in status or "RETIRED" in status:
                continue
        try:
            g = shape(feat["geometry"])
        except Exception:
            continue
        if g.is_empty:
            continue
        if not g.is_valid:
            g = g.buffer(0)
        try:
            voltage = float(props["VOLTAGE"]) if props.get("VOLTAGE") is not None else None
        except (TypeError, ValueError):
            voltage = None

        # Candidate counties via bbox
        for idx in tree.query(g):
            i = int(idx)
            if not prepared[i].intersects(g):
                continue
            inter = geoms[i].intersection(g)
            km = line_length_km(inter)
            if km <= 0:
                continue
            line_km[i] += km
            segments[i] += 1
            if voltage is not None and voltage >= HV_KV:
                hv_km[i] += km

    county_rows: dict[str, Any] = {}
    densities: list[float] = []
    for i, c in enumerate(counties):
        area = max(c["area_km2"], 1e-6)
        km = round(line_km[i], 2)
        hv = round(hv_km[i], 2)
        dens = km / area  # km per km²
        densities.append(dens)
        county_rows[c["name"].upper()] = {
            "name": c["name"],
            "geoid": c["geoid"],
            "area_km2": round(area, 2),
            "line_km": km,
            "hv_line_km": hv,
            "segment_hits": segments[i],
            "line_km_per_km2": round(dens, 6),
            "hv_share": round(hv / km, 4) if km > 0 else 0.0,
        }

    dens_sorted = sorted(densities)
    mid = len(dens_sorted) // 2
    median_dens = (
        dens_sorted[mid]
        if len(dens_sorted) % 2
        else (dens_sorted[mid - 1] + dens_sorted[mid]) / 2
    )

    payload = {
        "product": "site-clearance-wire-proxy-c0",
        "as_of": date.today().isoformat(),
        "source": {
            "name": "HIFLD Electric Power Transmission Lines",
            "url": (
                "https://services2.arcgis.com/FiaPA4ga0iQKduv3/arcgis/rest/services/"
                "US_Electric_Power_Transmission_Lines/FeatureServer/0"
            ),
            "note": (
                "Public approximate line geometries. Not CEII. Lengths are haversine "
                "estimates; density is relative across Texas counties, not a capacity rating."
            ),
        },
        "method": {
            "hv_kv_threshold": HV_KV,
            "length_unit": "km",
            "density_unit": "km_line_per_km2_county",
            "status_filter": "skip abandoned/proposed/retired when STATUS set",
        },
        "texas_median_line_km_per_km2": round(median_dens, 6),
        "county_count": len(county_rows),
        "line_features_used": len(features),
        "counties": county_rows,
    }
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Fetch one small page only")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    payload = build(dry_run=args.dry_run)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"Wrote {args.out} ({payload['county_count']} counties, "
        f"{payload['line_features_used']} line features, "
        f"median density={payload['texas_median_line_km_per_km2']})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

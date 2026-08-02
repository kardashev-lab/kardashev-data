"""Texas county polygons for Site Clearance spatial joins (no PostGIS)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def _as_polygonal(geom: BaseGeometry) -> BaseGeometry | None:
    """MapLibre fill layers need Polygon/MultiPolygon — not GeometryCollection."""
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        polys = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty]
        if not polys:
            return None
        return unary_union(polys)
    # Line/point leftovers from intersection — no fillable area
    return None

_GEOJSON_PATH = Path(__file__).resolve().parent.parent / "data" / "tx_counties.geojson"

# GIS CDR reporting zone -> ercot_zone_stats settlement load zone.
# COASTAL/PANHANDLE are not separate LZ_* hubs; map to nearest published LZ.
ZONE_TO_LZ = {
    "WEST": "LZ_WEST",
    "NORTH": "LZ_NORTH",
    "SOUTH": "LZ_SOUTH",
    "HOUSTON": "LZ_HOUSTON",
    "COASTAL": "LZ_HOUSTON",
    "PANHANDLE": "LZ_WEST",
}


@lru_cache(maxsize=1)
def _counties() -> list[dict[str, Any]]:
    raw = json.loads(_GEOJSON_PATH.read_text())
    out = []
    for feat in raw["features"]:
        geom = shape(feat["geometry"])
        if geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        name = str(feat["properties"]["name"]).strip()
        out.append({
            "name": name,
            "name_upper": name.upper(),
            "geoid": feat["properties"].get("geoid"),
            "geometry": geom,
            "area": float(geom.area),
        })
    return out


# Drop only numerical dust (deg²). Real corner clips must count — a 1% coverage
# floor was hiding intentional border overlaps on small search polygons.
_MIN_INTER_AREA = 1e-10

# Allow tiny coastline / float leftovers; reject Mexico / out-of-state spill.
_MAX_OUTSIDE_TEXAS_SHARE = 0.01


@lru_cache(maxsize=1)
def texas_boundary() -> BaseGeometry:
    union = unary_union([c["geometry"] for c in _counties()])
    if not union.is_valid:
        union = union.buffer(0)
    return union


def _prepare_search_polygon(polygon_geojson: dict) -> BaseGeometry:
    """Clean polygon and require it stay (almost) entirely inside Texas."""
    poly = shape(polygon_geojson)
    if poly.is_empty:
        raise ValueError("Polygon is empty.")
    if not poly.is_valid:
        poly = poly.buffer(0)
    poly_area = float(poly.area)
    if poly_area <= 0:
        raise ValueError("Polygon has no area.")

    texas = texas_boundary()
    inside = _as_polygonal(poly.intersection(texas))
    if inside is None or inside.is_empty:
        raise ValueError("Search area must be inside Texas.")

    outside_share = 1.0 - (float(inside.area) / poly_area)
    if outside_share > _MAX_OUTSIDE_TEXAS_SHARE:
        raise ValueError(
            "Search area extends outside Texas. Redraw so the whole polygon stays in Texas."
        )
    return poly


def intersect_counties(polygon_geojson: dict) -> list[dict[str, Any]]:
    """Return counties intersecting the polygon with area overlap weights.

    coverage = intersection_area / polygon_area — share of the search area in
    that county. overlap_weight = intersection_area / county_area — share of
    the county covered by the search. Projects are attributed at county
    resolution (no lat/lon pins).

    `geometry` is the intersection (what the search actually covers), not the
    full county — so map fill matches the counted footprint.

    Raises ValueError if the polygon spills outside Texas.
    """
    poly = _prepare_search_polygon(polygon_geojson)
    poly_area = float(poly.area)

    hits = []
    for c in _counties():
        if not poly.intersects(c["geometry"]):
            continue
        inter = poly.intersection(c["geometry"])
        inter_poly = _as_polygonal(inter)
        if inter_poly is None:
            continue
        inter_area = float(inter_poly.area)
        if inter_area < _MIN_INTER_AREA:
            continue
        weight = inter_area / c["area"] if c["area"] > 0 else 0.0
        coverage = inter_area / poly_area
        hits.append({
            "name": c["name"],
            "geoid": c["geoid"],
            "overlap_weight": round(min(max(weight, 0.0), 1.0), 6),
            "coverage": round(min(max(coverage, 0.0), 1.0), 6),
            # Overlap fill (inside search area) + full county outline for context.
            "geometry": mapping(inter_poly),
            "county_geometry": mapping(c["geometry"]),
            "intersection_geojson": mapping(inter_poly),
        })
    hits.sort(key=lambda h: h["coverage"], reverse=True)
    return hits


def counties_geojson() -> dict:
    """Full TX county FeatureCollection for map overlays."""
    return json.loads(_GEOJSON_PATH.read_text())


def union_county_names(hits: list[dict[str, Any]]) -> BaseGeometry | None:
    names = {h["name_upper"] if "name_upper" in h else h["name"].upper() for h in hits}
    geoms = [c["geometry"] for c in _counties() if c["name_upper"] in names]
    if not geoms:
        return None
    return unary_union(geoms)

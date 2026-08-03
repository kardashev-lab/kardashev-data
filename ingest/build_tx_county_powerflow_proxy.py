"""Build county-level GridSFM DC power-flow scenario summaries for Site Clearance C1.

Downloads Microsoft GridSFM Texas models (open OSM+EIA synthetic network — not ERCOT
CEII), maps buses to Texas counties, and for each county runs DC power-flow screening
scenarios: add load (withdrawal) or add generation (injection) at several MW levels
under peak (16h) and off-peak (04h) base cases.

Output: data/tx_county_powerflow_proxy.json (committed). Models stay in scratch/.

  python -m ingest.build_tx_county_powerflow_proxy
  python -m ingest.build_tx_county_powerflow_proxy --mw 200,500 --dry-run-counties Midland,Loving
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Optional

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent.parent
COUNTIES_PATH = ROOT / "data" / "tx_counties.geojson"
OUT_PATH = ROOT / "data" / "tx_county_powerflow_proxy.json"
SCRATCH = ROOT / "scratch" / "gridsfm"

HF_BASE = (
    "https://huggingface.co/datasets/microsoft/GridSFM_US_power_grid/resolve/main"
)
HOURS = ("16h", "04h")  # peak / off-peak GridSFM snapshots
DEFAULT_MW = (100, 200, 500, 1000)
OVERLOAD_PU = 1.0  # |flow| / rate_a


def _download(hour: str) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    dest = SCRATCH / f"texas_model_{hour}.json"
    if dest.exists() and dest.stat().st_size > 1_000_000:
        return dest
    url = f"{HF_BASE}/{hour}/texas_model.json"
    print(f"Downloading {url} …", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "kardashev-labs-c1/0.1"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        dest.write_bytes(resp.read())
    print(f"  wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)", flush=True)
    return dest


def load_counties() -> list[dict[str, Any]]:
    raw = json.loads(COUNTIES_PATH.read_text())
    out = []
    for feat in raw["features"]:
        geom = shape(feat["geometry"])
        if geom.is_empty:
            continue
        if not geom.is_valid:
            geom = geom.buffer(0)
        out.append(
            {
                "name": str(feat["properties"]["name"]).strip(),
                "geoid": feat["properties"].get("geoid"),
                "geometry": geom,
            }
        )
    return out


def assign_buses_to_counties(
    buses: dict[str, dict], counties: list[dict[str, Any]]
) -> tuple[dict[str, list[int]], list[str], dict[int, int]]:
    """Return county→bus-idxs, ordered bus keys, bus_i→idx (aligned with DcNetwork)."""
    geoms = [c["geometry"] for c in counties]
    tree = STRtree(geoms)
    bus_ids = sorted(buses.keys(), key=lambda k: int(buses[k]["bus_i"]))
    bus_i_to_idx = {int(buses[k]["bus_i"]): i for i, k in enumerate(bus_ids)}
    county_buses: dict[str, list[int]] = defaultdict(list)
    for k in bus_ids:
        b = buses[k]
        pt = Point(float(b["lon"]), float(b["lat"]))
        found = None
        for i in tree.query(pt):
            if geoms[int(i)].covers(pt):
                found = counties[int(i)]["name"]
                break
        if found:
            county_buses[found].append(bus_i_to_idx[int(b["bus_i"])])
    return dict(county_buses), bus_ids, bus_i_to_idx


class DcNetwork:
    """Sparse DC power-flow network from a GridSFM / PowerModels JSON."""

    def __init__(self, model: dict[str, Any]):
        self.base_mva = float(model.get("baseMVA") or 100.0)
        buses = model["bus"]
        self.bus_ids = sorted(buses.keys(), key=lambda k: int(buses[k]["bus_i"]))
        self.n = len(self.bus_ids)
        self.bus_i_to_idx = {int(buses[k]["bus_i"]): i for i, k in enumerate(self.bus_ids)}
        self.bus_type = np.array([int(buses[k]["bus_type"]) for k in self.bus_ids], dtype=int)
        self.base_kv = np.array([float(buses[k]["base_kv"]) for k in self.bus_ids])

        # Slack: prefer type 3, else largest generation bus
        slack_candidates = np.where(self.bus_type == 3)[0]
        if len(slack_candidates) == 0:
            # Fall back later after building P
            self.slack = 0
        else:
            self.slack = int(slack_candidates[0])

        # Net injection P (pu): gen - load
        p = np.zeros(self.n)
        for g in model["gen"].values():
            if int(g.get("gen_status", 1)) != 1:
                continue
            bi = int(g["gen_bus"])
            if bi not in self.bus_i_to_idx:
                continue
            p[self.bus_i_to_idx[bi]] += float(g.get("pg") or 0.0)
        for ld in model["load"].values():
            if int(ld.get("status", 1)) != 1:
                continue
            bi = int(ld["load_bus"])
            if bi not in self.bus_i_to_idx:
                continue
            p[self.bus_i_to_idx[bi]] -= float(ld.get("pd") or 0.0)
        self.p_base = p

        if len(slack_candidates) == 0:
            self.slack = int(np.argmax(np.abs(self.p_base)))

        # Branches
        f_list: list[int] = []
        t_list: list[int] = []
        x_list: list[float] = []
        rate_list: list[float] = []
        status_list: list[int] = []
        names: list[str] = []
        for br in model["branch"].values():
            if int(br.get("br_status", 1)) != 1:
                continue
            fb = int(br["f_bus"])
            tb = int(br["t_bus"])
            if fb not in self.bus_i_to_idx or tb not in self.bus_i_to_idx:
                continue
            x = float(br.get("br_x") or 0.0)
            if abs(x) < 1e-8:
                continue
            rate = float(br.get("rate_a") or 0.0)
            if rate <= 0:
                # Unrated — skip for overload stats (still include in network)
                rate = 1e9
            f_list.append(self.bus_i_to_idx[fb])
            t_list.append(self.bus_i_to_idx[tb])
            x_list.append(x)
            rate_list.append(rate)
            status_list.append(1)
            names.append(str(br.get("circuit_key") or br.get("index")))

        self.f = np.array(f_list, dtype=int)
        self.t = np.array(t_list, dtype=int)
        self.x = np.array(x_list, dtype=float)
        self.rate = np.array(rate_list, dtype=float)
        self.br_names = names
        self.m = len(f_list)

        # Bbus susceptance matrix
        b_ij = 1.0 / self.x
        data = np.concatenate([-b_ij, -b_ij, b_ij, b_ij])
        rows = np.concatenate([self.f, self.t, self.f, self.t])
        cols = np.concatenate([self.t, self.f, self.f, self.t])
        self.B = sparse.coo_matrix((data, (rows, cols)), shape=(self.n, self.n)).tocsc()

        # Keep factorization pattern: reduce by removing slack
        keep = [i for i in range(self.n) if i != self.slack]
        self._keep = np.array(keep, dtype=int)
        self._Bred = self.B[self._keep][:, self._keep].tocsc()

    def local_branch_mask(self, bus_idxs: list[int], hops: int = 1) -> np.ndarray:
        """Branches with an endpoint in the county bus set (optionally 1-hop expanded)."""
        seed = set(bus_idxs)
        if hops >= 1 and seed:
            expanded = set(seed)
            for f, t in zip(self.f, self.t):
                if int(f) in seed or int(t) in seed:
                    expanded.add(int(f))
                    expanded.add(int(t))
            seed = expanded
        mask = np.zeros(self.m, dtype=bool)
        if not seed:
            return mask
        for j in range(self.m):
            if int(self.f[j]) in seed or int(self.t[j]) in seed:
                mask[j] = True
        return mask

    def solve(self, p: np.ndarray) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Return (theta, branch_flow_pu) or (None, None) if singular."""
        pred = p[self._keep].copy()
        try:
            theta_red = spsolve(self._Bred, pred)
        except Exception:
            return None, None
        if theta_red is None or not np.all(np.isfinite(theta_red)):
            return None, None
        theta = np.zeros(self.n)
        theta[self._keep] = theta_red
        flow = (theta[self.f] - theta[self.t]) / self.x
        return theta, flow

    def loading(self, flow: np.ndarray) -> np.ndarray:
        return np.abs(flow) / np.maximum(self.rate, 1e-9)


def scenario_stats(
    net: DcNetwork,
    flow: np.ndarray,
    *,
    branch_mask: Optional[np.ndarray] = None,
    base_flow: Optional[np.ndarray] = None,
) -> dict[str, Any]:
    loading = net.loading(flow)
    rated = net.rate < 1e8
    mask = rated if branch_mask is None else (rated & branch_mask)
    if not np.any(mask):
        return {
            "converged": True,
            "max_loading_pu": None,
            "overload_count": 0,
            "rated_branch_count": 0,
            "overload_rate": None,
            "p95_loading_pu": None,
            "top_branches": [],
            "scope": "empty",
        }
    load_r = loading[mask]
    over = load_r >= OVERLOAD_PU
    idxs = np.where(mask)[0]
    order = idxs[np.argsort(-loading[idxs])]
    top = []
    for j in order[:5]:
        entry = {
            "branch": net.br_names[j],
            "loading_pu": round(float(loading[j]), 3),
            "flow_mw": round(float(flow[j] * net.base_mva), 1),
            "rate_mva": round(float(net.rate[j] * net.base_mva), 1),
        }
        if base_flow is not None:
            entry["delta_flow_mw"] = round(
                float((flow[j] - base_flow[j]) * net.base_mva), 1
            )
        top.append(entry)
    return {
        "converged": True,
        "max_loading_pu": round(float(load_r.max()), 3),
        "overload_count": int(over.sum()),
        "rated_branch_count": int(mask.sum()),
        "overload_rate": round(float(over.mean()), 4),
        "p95_loading_pu": round(float(np.percentile(load_r, 95)), 3),
        "top_branches": top,
        "scope": "local" if branch_mask is not None else "system",
    }


def _distribute_mw(net: DcNetwork, bus_idxs: list[int], mw: float, sign: int) -> np.ndarray:
    """sign=+1 injection (gen), sign=-1 withdrawal (load). Returns delta P in pu."""
    delta = np.zeros(net.n)
    if not bus_idxs or mw <= 0:
        return delta
    weights = np.array([max(net.base_kv[i], 69.0) for i in bus_idxs], dtype=float)
    weights = weights / weights.sum()
    pu = (mw / net.base_mva) * sign
    for i, w in zip(bus_idxs, weights):
        delta[i] += pu * w
    return delta


def level_from_local(stats_list: list[dict[str, Any]]) -> str:
    """Level from local-branch perturb scenarios (not system-wide bottlenecks)."""
    usable = [s for s in stats_list if s.get("max_loading_pu") is not None]
    if not usable:
        return "unknown"
    max_load = max(float(s["max_loading_pu"]) for s in usable)
    max_delta = max(float(s.get("delta_max_loading_pu") or 0) for s in usable)
    max_abs_delta = max(float(s.get("max_abs_delta_loading_pu") or 0) for s in usable)
    over_any = sum(1 for s in usable if (s.get("overload_count") or 0) > 0)
    impact = max(max_delta, max_abs_delta)
    if max_load >= 1.0 or impact >= 0.15 or over_any >= max(2, len(usable) // 2):
        return "stressed"
    if max_load >= 0.75 or impact >= 0.05 or over_any >= 1:
        return "moderate"
    return "calm"


def run_county_scenarios(
    nets: dict[str, DcNetwork],
    county_buses: dict[str, list[int]],
    county: str,
    mw_levels: list[float],
) -> dict[str, Any]:
    buses = county_buses.get(county) or []
    if not buses:
        return {
            "bus_count": 0,
            "level": "unknown",
            "note": "No GridSFM buses mapped into this county.",
            "scenarios": [],
        }

    scenarios: list[dict[str, Any]] = []
    for hour, net in nets.items():
        local = net.local_branch_mask(buses, hops=1)
        base_theta, base_flow = net.solve(net.p_base)
        if base_flow is None:
            continue
        base = scenario_stats(net, base_flow, branch_mask=local)
        base["hour"] = hour
        base["mode"] = "base"
        base["mw"] = 0
        scenarios.append(base)

        for mw in mw_levels:
            for mode, sign in (("withdrawal", -1), ("injection", +1)):
                p = net.p_base + _distribute_mw(net, buses, mw, sign)
                _, flow = net.solve(p)
                if flow is None:
                    scenarios.append(
                        {
                            "hour": hour,
                            "mode": mode,
                            "mw": mw,
                            "converged": False,
                            "max_loading_pu": None,
                            "overload_count": None,
                            "overload_rate": None,
                            "p95_loading_pu": None,
                            "top_branches": [],
                            "scope": "local",
                        }
                    )
                    continue
                st = scenario_stats(
                    net, flow, branch_mask=local, base_flow=base_flow
                )
                st["hour"] = hour
                st["mode"] = mode
                st["mw"] = mw
                st["delta_max_loading_pu"] = (
                    round(st["max_loading_pu"] - base["max_loading_pu"], 3)
                    if st["max_loading_pu"] is not None and base["max_loading_pu"] is not None
                    else None
                )
                # Peak local impact: largest |Δ loading| on any local rated branch
                if base_flow is not None:
                    base_ld = net.loading(base_flow)
                    new_ld = net.loading(flow)
                    rated_local = local & (net.rate < 1e8)
                    if np.any(rated_local):
                        st["max_abs_delta_loading_pu"] = round(
                            float(np.max(np.abs(new_ld - base_ld)[rated_local])), 3
                        )
                    else:
                        st["max_abs_delta_loading_pu"] = None
                else:
                    st["max_abs_delta_loading_pu"] = None
                st["delta_overload_count"] = (
                    (st["overload_count"] or 0) - (base["overload_count"] or 0)
                )
                scenarios.append(st)

    perturb = [s for s in scenarios if s.get("mode") != "base" and s.get("converged")]
    return {
        "bus_count": len(buses),
        "local_branch_count": int(
            nets["16h"].local_branch_mask(buses, hops=1).sum()
        )
        if "16h" in nets
        else None,
        "level": level_from_local(perturb),
        "scenarios": scenarios,
    }


def build(
    mw_levels: list[float],
    only_counties: Optional[set[str]] = None,
) -> dict[str, Any]:
    counties = load_counties()
    nets: dict[str, DcNetwork] = {}
    county_buses: dict[str, list[int]] = {}

    for hour in HOURS:
        path = _download(hour)
        model = json.loads(path.read_text())
        print(f"Building DC network for {hour} ({model.get('target_datetime')})…", flush=True)
        net = DcNetwork(model)
        nets[hour] = net
        if not county_buses:
            cb, _, _ = assign_buses_to_counties(model["bus"], counties)
            county_buses = cb
            print(
                f"  buses={net.n} branches={net.m} counties_with_buses={len(county_buses)}",
                flush=True,
            )

    names = [c["name"] for c in counties]
    if only_counties:
        names = [n for n in names if n in only_counties]

    out_counties: dict[str, Any] = {}
    for i, name in enumerate(names):
        if i % 25 == 0:
            print(f"  county {i+1}/{len(names)}: {name}", flush=True)
        result = run_county_scenarios(nets, county_buses, name, mw_levels)
        # Compact: keep summary + worst scenarios, not every top_branches for all MW
        compact_scenarios = []
        for s in result["scenarios"]:
            compact_scenarios.append(
                {
                    "hour": s["hour"],
                    "mode": s["mode"],
                    "mw": s["mw"],
                    "converged": s.get("converged"),
                    "max_loading_pu": s.get("max_loading_pu"),
                    "overload_count": s.get("overload_count"),
                    "overload_rate": s.get("overload_rate"),
                    "p95_loading_pu": s.get("p95_loading_pu"),
                    "delta_max_loading_pu": s.get("delta_max_loading_pu"),
                    "max_abs_delta_loading_pu": s.get("max_abs_delta_loading_pu"),
                    "delta_overload_count": s.get("delta_overload_count"),
                    "rated_branch_count": s.get("rated_branch_count"),
                    "top_branches": s.get("top_branches", [])[:3],
                }
            )
        # Pick representative worst withdrawal @ 500 MW peak if present
        worst = None
        for s in compact_scenarios:
            if s["mode"] == "withdrawal" and s["mw"] == 500 and s["hour"] == "16h":
                worst = s
                break
        if worst is None and compact_scenarios:
            pert = [s for s in compact_scenarios if s["mode"] != "base" and s.get("max_loading_pu") is not None]
            if pert:
                worst = max(pert, key=lambda s: s["max_loading_pu"] or 0)

        out_counties[name.upper()] = {
            "name": name,
            "bus_count": result["bus_count"],
            "local_branch_count": result.get("local_branch_count"),
            "level": result["level"],
            "worst_withdrawal_500mw_peak": worst,
            "scenarios": compact_scenarios,
        }

    # Texas-wide base reference from first net
    ref_net = nets["16h"]
    _, ref_flow = ref_net.solve(ref_net.p_base)
    ref_stats = scenario_stats(ref_net, ref_flow) if ref_flow is not None else {}

    return {
        "product": "site-clearance-powerflow-proxy-c1",
        "as_of": date.today().isoformat(),
        "source": {
            "name": "Microsoft GridSFM US power grid — Texas",
            "url": "https://huggingface.co/datasets/microsoft/GridSFM_US_power_grid",
            "hours": list(HOURS),
            "note": (
                "Synthetic open network from OSM + EIA (not ERCOT CEII / planning models). "
                "DC power-flow screening only. Slack absorbs imbalance. Not an official "
                "interconnection or contingency study."
            ),
        },
        "method": {
            "formulation": "DC power flow (B-theta)",
            "mw_levels": list(mw_levels),
            "modes": ["base", "withdrawal", "injection"],
            "overload_threshold_pu": OVERLOAD_PU,
            "distribution": "MW spread across county buses weighted by base_kv",
            "level_rule": (
                "On local branches (county buses + 1 hop): stressed if local max loading "
                "≥1.0 pu or max(|Δ loading|) ≥0.15 or overloads in ≥half of perturb scenarios; "
                "moderate if local max ≥0.75 or max(|Δ loading|) ≥0.05 or any overload; else calm"
            ),
            "local_scope": "branches incident to county buses or adjacent buses (1 hop)",
        },
        "base_peak_16h_system": ref_stats,
        "county_count": len(out_counties),
        "counties": out_counties,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mw", default=",".join(str(m) for m in DEFAULT_MW))
    ap.add_argument(
        "--dry-run-counties",
        default="",
        help="Comma-separated county names to run only (for testing)",
    )
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()
    mw_levels = [float(x) for x in args.mw.split(",") if x.strip()]
    only = {x.strip() for x in args.dry_run_counties.split(",") if x.strip()} or None

    payload = build(mw_levels, only_counties=only)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"Wrote {args.out} ({payload['county_count']} counties, "
        f"mw={mw_levels})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

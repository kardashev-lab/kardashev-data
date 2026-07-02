"""
Run in Railway (Python 3.12) to probe what gridstatus returns for each ISO.
Usage:  railway run python scripts/probe_gridstatus.py
"""
import gridstatus

for iso_name, cls in [("CAISO", gridstatus.CAISO), ("ERCOT", gridstatus.ERCOT)]:
    print(f"\n=== {iso_name} ===")
    try:
        iso = cls()
        df = iso.get_lmp(date="latest", market="REAL_TIME_5_MIN", locations="ALL")
        print(f"  rows={len(df)}  cols={list(df.columns)}")
        print(df.head(5).to_string())
    except Exception as e:
        print(f"  ERROR: {e}")

"""Parse and clean TransLink GTFS tables. See CONTRACT.md and data/PROFILE.md."""
import re
import zipfile

import numpy as np
import pandas as pd

# 'H:MM:SS' with plain ASCII digits only; hours may exceed 24 (after-midnight trips).
_TIME_RE = re.compile(r"([0-9]+):([0-9]+):([0-9]+)")
MAX_HOURS = 47
STOP_COLUMNS = ["stop_id", "stop_name", "stop_lat", "stop_lon"]
BOARDABLE = {"0", ""}  # location_type: 0 = stop/platform, blank = stop; 1 station, 2 entrance


def parse_gtfs_time(s: str) -> int | None:
    """One GTFS time -> seconds since the service day's midnight, or None if invalid."""
    if not isinstance(s, str):
        return None
    m = _TIME_RE.fullmatch(s.strip())
    if m is None:
        return None
    try:
        h, mins, secs = (int(g) for g in m.groups())
    except ValueError:  # thousands of digits exceed Python's int-conversion limit
        return None
    if h > MAX_HOURS or mins >= 60 or secs >= 60:
        return None
    return h * 3600 + mins * 60 + secs


def parse_gtfs_times(times: pd.Series) -> pd.Series:
    """Whole-column parse_gtfs_time -> nullable Int32, same index.

    1.8M stop_times hold only ~87k distinct strings, so parse each distinct value once
    (same rules as parse_gtfs_time) and map the results back by code.
    """
    codes, uniques = pd.factorize(times, use_na_sentinel=True)
    # One extra trailing <NA> so code -1 (a missing input) indexes to it.
    parsed = pd.array([parse_gtfs_time(u) for u in uniques] + [None], dtype="Int32")
    return pd.Series(parsed[codes], index=times.index, dtype="Int32", name=times.name)


def load_stops(zf: zipfile.ZipFile) -> pd.DataFrame:
    """Boardable stops from stops.txt: stop_id (text), stop_name, stop_lat, stop_lon.

    Caller must have run fetch_gtfs.validate_zip on the archive (member size caps).
    """
    with zf.open("stops.txt") as f:
        df = pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    if "location_type" in df:
        df = df[df["location_type"].isin(BOARDABLE)]
    lat = pd.to_numeric(df["stop_lat"], errors="coerce")
    lon = pd.to_numeric(df["stop_lon"], errors="coerce")
    ok = np.isfinite(lat) & np.isfinite(lon)  # drops blank, non-numeric, nan and inf
    out = df.loc[ok, ["stop_id", "stop_name"]].assign(
        stop_lat=lat[ok].astype("float64"), stop_lon=lon[ok].astype("float64")
    )
    return out[STOP_COLUMNS].reset_index(drop=True)

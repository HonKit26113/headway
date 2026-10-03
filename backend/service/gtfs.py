"""Parse and clean TransLink GTFS tables. See CONTRACT.md and data/PROFILE.md."""
import datetime as dt
import re
import zipfile

import numpy as np
import pandas as pd

# 'H:MM:SS' with plain ASCII digits only; hours may exceed 24 (after-midnight trips).
_TIME_RE = re.compile(r"([0-9]+):([0-9]+):([0-9]+)")
MAX_HOURS = 47
STOP_COLUMNS = ["stop_id", "stop_name", "stop_lat", "stop_lon"]
BOARDABLE = {"0", ""}  # location_type: 0 = stop/platform, blank = stop; 1 station, 2 entrance
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TRIP_COLUMNS = ["trip_id", "route_id", "service_id", "direction_id"]
DAY_START, DAY_END = 7 * 3600, 19 * 3600  # headway window: 07:00 <= t < 19:00
DAY_WINDOW_MIN = (DAY_END - DAY_START) // 60
DAY_WINDOW_HOURS = (DAY_END - DAY_START) / 3600
LATE_NIGHT = 23 * 3600


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


def read_table(zf: zipfile.ZipFile, name: str, **kw) -> pd.DataFrame:
    """A GTFS table as all-text columns (blank stays '', 'NA' stays 'NA')."""
    with zf.open(name) as f:
        return pd.read_csv(f, dtype=str, keep_default_na=False, encoding="utf-8-sig", **kw)


def active_service_ids(zf: zipfile.ZipFile, date: str) -> set[str]:
    """Service ids running on `date` ('YYYYMMDD'): calendar.txt + calendar_dates.txt adds - removes."""
    if not re.fullmatch(r"[0-9]{8}", date):
        raise ValueError(f"date must be YYYYMMDD, got {date!r}")
    weekday = WEEKDAYS[dt.datetime.strptime(date, "%Y%m%d").weekday()]
    names = set(zf.namelist())
    active: set[str] = set()
    if "calendar.txt" in names:
        cal = read_table(zf, "calendar.txt")
        dated = (cal["start_date"] != "") & (cal["end_date"] != "")  # a blank date never runs
        runs = dated & (cal[weekday] == "1") & (cal["start_date"] <= date) & (cal["end_date"] >= date)
        active = set(cal.loc[runs, "service_id"])
    if "calendar_dates.txt" in names:
        cd = read_table(zf, "calendar_dates.txt")
        today = cd[cd["date"] == date]
        active |= set(today.loc[today["exception_type"] == "1", "service_id"])
        active -= set(today.loc[today["exception_type"] == "2", "service_id"])
    return active


def load_trips(zf: zipfile.ZipFile) -> pd.DataFrame:
    """trips.txt -> [trip_id, route_id, service_id, direction_id], all text."""
    trips = read_table(zf, "trips.txt")
    if "direction_id" not in trips:
        trips["direction_id"] = ""
    return trips[TRIP_COLUMNS].reset_index(drop=True)


def _clock_label(minutes: int) -> str:
    """Minutes after service-day midnight -> 12-hour clock, e.g. 1530 -> '1:30 AM'."""
    h, m = divmod(minutes % 1440, 60)
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def build_stop_stats(stop_times: pd.DataFrame, trips: pd.DataFrame, service_ids: set[str]) -> dict[str, dict]:
    """Per-stop frequency, last bus and trip counts for one service day. See CONTRACT.md."""
    active = trips.loc[trips["service_id"].isin(service_ids), ["trip_id", "route_id", "direction_id"]]
    active = active.assign(direction_id=active["direction_id"].fillna(""))  # missing groups with ''
    boardable = stop_times["departure_s"].notna()
    if "pickup_type" in stop_times:
        boardable &= stop_times["pickup_type"] != "1"  # '1' = no pickup, e.g. a trip's last stop
    dep = stop_times.loc[boardable, ["trip_id", "stop_id", "departure_s"]].merge(
        active, on="trip_id", validate="many_to_one"  # duplicate trip_ids would double-count -> MergeError
    )
    if dep.empty:
        return {}
    secs = dep["departure_s"].astype("int64")
    by_stop = secs.groupby(dep["stop_id"], observed=True)
    count, last = by_stop.size(), by_stop.max()
    late = (secs >= LATE_NIGHT).groupby(dep["stop_id"], observed=True).sum()
    daytime = dep[(secs >= DAY_START) & (secs < DAY_END)]
    per_hour = daytime.groupby("stop_id", observed=True).size() / DAY_WINDOW_HOURS
    best = (
        daytime.groupby(["stop_id", "route_id", "direction_id"], observed=True, dropna=False)
        .size()
        .groupby(level="stop_id", observed=True)
        .max()
    )

    stats = {}
    for stop_id in count.index:
        last_min = int(last[stop_id]) // 60
        stats[str(stop_id)] = {
            "headway_min": round(DAY_WINDOW_MIN / int(best[stop_id]), 1) if stop_id in best.index else None,
            "departures_per_hour": round(float(per_hour.get(stop_id, 0.0)), 1),
            "trips_per_day": int(count[stop_id]),
            "last_departure_min": last_min,
            "last_departure_label": _clock_label(last_min),
            "late_trips_after_23": int(late[stop_id]),
        }
    return stats

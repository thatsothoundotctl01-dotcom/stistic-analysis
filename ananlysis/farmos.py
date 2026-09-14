"""
FarmOS Weekly Report — greenhouse_stats (SINGLE-FILE VERSION)
================================================================

Computes the weekly report for Kampot Farm's cooling/spraying system
(Environment, Actuators, Data Health, Effectiveness). This file merges
every module from the original `greenhouse_stats` package
(io_utils, data_health, environment, actuators, effectiveness,
profile, report) plus the CLI and the `make_deliverables.py`
figure/JSON-generation script into one standalone script.

USAGE
-----
1) Just the weekly JSON report (mirrors `python -m greenhouse_stats`):

    python farmos_report_single_file.py --csv DATA.csv --start 2026-05-11 --out week2_report.json
    Optional flags: --threshold 35.0 (C), --flow-rate 2.0 (L/min)

2) Full deliverables — profile JSONs + 4 figures (mirrors `make_deliverables.py`):

    python farmos_report_single_file.py --deliverables --csv DATA.csv

   Figures are written to ./figures/ and JSON files to the current
   directory, matching the original project's layout.

ASSUMPTIONS (see decision_log.md in the original project for the why)
-----------------------------------------------------------------------
- Pump flow rate: 2.0 L/min (no hardware-team figure — configurable via --flow-rate)
- Temperature threshold: 35.0 C, humidity: 70% (configurable via --threshold)
- Gap threshold: 300s (5 min) counts as a logger outage
"""

from __future__ import annotations

import argparse
import json
import os

import pandas as pd


# ======================================================================
# io_utils.py — Loading and basic preparation of the raw sensor CSV
# ======================================================================
#
# The raw file has irregular sampling (intervals from a fraction of a
# second to many days), so every downstream computation works from a
# 'duration_s' column: how long (in seconds) each reading's state was
# in effect, i.e. the time until the *next* reading arrives. This is
# what makes duty cycles, uptime, etc. time-weighted instead of
# row-weighted.

def load_data(csv_path: str) -> pd.DataFrame:
    """Load, parse, sort and prepare the raw sensor CSV.

    Parameters
    ----------
    csv_path : str
        Path to the raw CSV with columns time, temperature, humidity,
        relay1, relay2, relay3.

    Returns
    -------
    pd.DataFrame
        Sorted by time (tz-aware, Asia/Bangkok), with an added
        'duration_s' column: seconds until the next reading. The last
        row's duration is NaN (no following reading).
    """
    df = pd.read_csv(csv_path)
    df["time"] = pd.to_datetime(df["time"], format="mixed")
    df = df.sort_values("time").reset_index(drop=True)

    # Sanity check: are timestamps monotonic after sorting?
    n_out_of_order = (df["time"].diff().dt.total_seconds() < 0).sum()
    if n_out_of_order:
        raise ValueError(
            f"{n_out_of_order} out-of-order timestamp(s) found after "
            "sorting — investigate before trusting downstream numbers."
        )

    df["duration_s"] = df["time"].diff().shift(-1).dt.total_seconds()
    return df


def slice_window(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Return the rows with time in [start, end), tz-aware.

    Parameters
    ----------
    df : pd.DataFrame
        Output of load_data().
    start, end : str or pd.Timestamp
        Window boundaries. Naive strings are localised to Asia/Bangkok.

    Returns
    -------
    pd.DataFrame
        Copy of the matching rows, index reset.
    """
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if start.tzinfo is None:
        start = start.tz_localize("Asia/Bangkok")
    if end.tzinfo is None:
        end = end.tz_localize("Asia/Bangkok")

    mask = (df["time"] >= start) & (df["time"] < end)
    return df.loc[mask].reset_index(drop=True)


# ======================================================================
# data_health.py — Group C: uptime, gaps, timestamp anomalies
# ======================================================================
#
# Everything here answers: how much of this window can we actually
# trust, and where are the holes? Every other module depends on the
# 'logged_duration_s' this module defines.

def find_gaps(df: pd.DataFrame, gap_threshold_s: float = 300) -> pd.DataFrame:
    """Identify gaps longer than gap_threshold_s between consecutive readings.

    Returns
    -------
    pd.DataFrame
        Columns: gap_start (time of the reading before the gap),
        duration_s. Empty DataFrame if no gaps.
    """
    mask = df["duration_s"] > gap_threshold_s
    gaps = df.loc[mask, ["time", "duration_s"]].rename(columns={"time": "gap_start"})
    return gaps.reset_index(drop=True)


def compute_uptime(
    df: pd.DataFrame,
    window_start,
    window_end,
    gap_threshold_s: float = 300,
) -> dict:
    """Compute logger uptime for a window, correctly.

    Two bugs this function specifically avoids:

    1. The 'span' trap: computing uptime as
       (last_reading - first_reading) / window_length silently ignores
       gaps *inside* the window.

    2. The 'boundary overflow' trap: a window's last reading's
       duration_s is measured to the *next real reading in the whole
       dataset*, which can be far outside this window. Counting that
       entire duration as a "gap inside this window" can push total
       gap time above the window length and produce a negative or
       nonsensical uptime. This function clips every duration at the
       window boundary before summing gaps, and separately counts any
       dead time before the first reading or after the last reading
       as outage time too.

    Returns
    -------
    dict with keys:
        uptime_percent, logged_duration_s, gaps, n_gaps, total_gap_hours,
        leading_gap_hours, trailing_gap_hours
    """
    window_seconds = (window_end - window_start).total_seconds()

    if len(df) == 0:
        return {
            "uptime_percent": 0.0, "logged_duration_s": 0.0,
            "gaps": pd.DataFrame(columns=["gap_start", "duration_s"]),
            "n_gaps": 0, "total_gap_hours": 0.0,
            "leading_gap_hours": round(window_seconds / 3600, 2),
            "trailing_gap_hours": 0.0,
        }

    # clip each row's duration so it never extends past window_end
    clipped = df["duration_s"].copy()
    time_to_end = (window_end - df["time"]).dt.total_seconds()
    clipped = clipped.clip(upper=time_to_end)
    clipped = clipped.clip(lower=0)

    internal_gap_mask = clipped > gap_threshold_s
    internal_gaps = df.loc[internal_gap_mask, ["time"]].rename(columns={"time": "gap_start"})
    internal_gaps["duration_s"] = clipped[internal_gap_mask]
    internal_gap_s = clipped[internal_gap_mask].sum()

    leading_gap_s = max(0.0, (df["time"].iloc[0] - window_start).total_seconds())
    last_duration = df["duration_s"].iloc[-1]
    last_duration = 0 if pd.isna(last_duration) else last_duration
    last_end = df["time"].iloc[-1] + pd.Timedelta(seconds=last_duration)
    last_end = min(last_end, window_end)
    trailing_gap_s = max(0.0, (window_end - last_end).total_seconds())

    total_gap_s = internal_gap_s + leading_gap_s + trailing_gap_s
    logged_duration_s = window_seconds - total_gap_s
    uptime_percent = 100 * logged_duration_s / window_seconds

    return {
        "uptime_percent": round(uptime_percent, 2),
        "logged_duration_s": logged_duration_s,
        "gaps": internal_gaps.reset_index(drop=True),
        "n_gaps": len(internal_gaps),
        "total_gap_hours": round(total_gap_s / 3600, 2),
        "leading_gap_hours": round(leading_gap_s / 3600, 2),
        "trailing_gap_hours": round(trailing_gap_s / 3600, 2),
    }


def timestamp_anomalies(df: pd.DataFrame) -> dict:
    """Flag timestamp irregularities worth mentioning in the report.

    Returns
    -------
    dict with keys:
        n_duplicate_timestamps : int
        n_subsecond_intervals : int — readings arriving < 1s after previous
        min_interval_s : float
        max_interval_s : float
    """
    dur = df["duration_s"].dropna()
    return {
        "n_duplicate_timestamps": int((dur == 0).sum()),
        "n_subsecond_intervals": int(((dur > 0) & (dur < 1)).sum()),
        "min_interval_s": float(dur.min()) if len(dur) else None,
        "max_interval_s": float(dur.max()) if len(dur) else None,
    }


# ======================================================================
# environment.py — Group A: temperature and humidity
# ======================================================================
#
# Median/IQR are used throughout instead of mean/std because the data
# profile shows temperature is left-skewed and humidity is
# right-skewed — the mean is pulled away from the 'typical' reading in
# a skewed distribution.

def median_iqr(series: pd.Series) -> dict:
    """Median and IQR (25th/75th percentile) of a numeric series."""
    q1, med, q3 = series.quantile([0.25, 0.5, 0.75])
    return {"median": round(med, 2), "iqr": [round(q1, 2), round(q3, 2)]}


def min_max_with_times(df: pd.DataFrame, column: str) -> dict:
    """Minimum and maximum of `column`, with the timestamps they occurred at."""
    imin = df[column].idxmin()
    imax = df[column].idxmax()
    return {
        "min": float(df.loc[imin, column]),
        "min_at": df.loc[imin, "time"].isoformat(),
        "max": float(df.loc[imax, column]),
        "max_at": df.loc[imax, "time"].isoformat(),
    }


def percent_time_above_threshold(
    df: pd.DataFrame, column: str, threshold: float, logged_duration_s: float
) -> float:
    """% of *logged* time that `column` was above `threshold`.

    Denominator is logged_duration_s (from compute_uptime), not the
    full window — an unlogged period tells us nothing about whether
    the threshold was exceeded, so it must not silently count as "not
    above threshold".
    """
    dur = df["duration_s"].where(df["duration_s"] <= 300, other=0)  # exclude gap rows
    above = dur[df[column] > threshold].sum()
    return round(100 * above / logged_duration_s, 2) if logged_duration_s else None


def longest_spell_above_threshold(df: pd.DataFrame, column: str, threshold: float) -> dict:
    """Longest continuous spell where `column` stayed above `threshold`.

    A spell is broken by either a reading dropping back at/below
    threshold, OR a logger gap (>300s) — we cannot claim a spell
    continued through a period we didn't observe.
    """
    above = df[column] > threshold
    gap_break = df["duration_s"].fillna(0) > 300
    # a new spell group starts whenever 'above' changes OR a gap interrupts
    group_break = above.ne(above.shift()) | gap_break.shift(fill_value=False)
    group_id = group_break.cumsum()

    best_hours = 0.0
    best_start = None
    best_end = None
    for gid, sub in df.groupby(group_id):
        if not above.loc[sub.index].iloc[0]:
            continue
        dur = sub["duration_s"].where(sub["duration_s"] <= 300, other=0).sum()
        if dur > best_hours * 3600:
            best_hours = dur / 3600
            best_start = sub["time"].iloc[0]
            best_end = sub["time"].iloc[-1]

    return {
        "hours": round(best_hours, 2),
        "start": best_start.isoformat() if best_start is not None else None,
        "end": best_end.isoformat() if best_end is not None else None,
    }


def environment_summary(
    df: pd.DataFrame, column: str, threshold: float, logged_duration_s: float
) -> dict:
    """Bundle all Group A metrics for one column (temperature or humidity)."""
    out = median_iqr(df[column])
    out.update(min_max_with_times(df, column))
    out["percent_time_above_threshold"] = percent_time_above_threshold(
        df, column, threshold, logged_duration_s
    )
    out["threshold"] = threshold
    out["longest_spell_above_threshold"] = longest_spell_above_threshold(df, column, threshold)
    out["skew"] = round(float(df[column].skew()), 3)
    return out


# ======================================================================
# actuators.py — Group B: relay1 (cooling) / relay3 (spray pump)
# ======================================================================
#
# THE RULE THAT GOVERNS THIS SECTION:
# Readings are not evenly spaced, so `df['relay3'].mean()` is the
# proportion of ROWS that are ON, not the proportion of TIME. Every
# function below is time-weighted: durations are summed, not rows
# counted. Rows whose duration spans a logger gap (>gap_threshold_s)
# are excluded from the "known" time rather than guessed at.

def duty_cycle(df: pd.DataFrame, relay_col: str, gap_threshold_s: float = 300) -> dict:
    """Time-weighted duty cycle of a relay column.

    Returns
    -------
    dict with keys:
        duty_cycle_percent : float — % of *logged* time the relay was ON
        on_minutes : float
        logged_minutes : float
    """
    known = df["duration_s"].where(df["duration_s"] <= gap_threshold_s)
    logged_s = known.sum(skipna=True)
    on_s = (known * df[relay_col]).sum(skipna=True)
    pct = 100 * on_s / logged_s if logged_s else None
    return {
        "duty_cycle_percent": round(pct, 2) if pct is not None else None,
        "on_minutes": round(on_s / 60, 2),
        "logged_minutes": round(logged_s / 60, 2),
    }


def count_activations(df: pd.DataFrame, relay_col: str) -> int:
    """Count OFF->ON transitions (activations), not every state change."""
    return int((df[relay_col].diff() == 1).sum())


def extract_events(df: pd.DataFrame, relay_col: str, gap_threshold_s: float = 300) -> pd.DataFrame:
    """Turn a relay column into a table of discrete ON events.

    Each row of the output is one continuous ON stretch. An event that
    is interrupted by a logger gap is flagged via `spans_gap` rather
    than silently merged or split.

    Returns
    -------
    pd.DataFrame with columns:
        start, end, duration_s, duration_min, spans_gap
    """
    state = df[relay_col]
    group_id = state.ne(state.shift()).cumsum()

    events = []
    for gid, sub in df.groupby(group_id):
        if state.loc[sub.index].iloc[0] != 1:
            continue
        spans_gap = bool((sub["duration_s"] > gap_threshold_s).any())
        # duration = sum of each row's time-in-state, capping any gap row
        dur = sub["duration_s"].where(sub["duration_s"] <= gap_threshold_s, other=0).sum()
        events.append(
            {
                "start": sub["time"].iloc[0],
                "end": sub["time"].iloc[-1],
                "duration_s": dur,
                "duration_min": round(dur / 60, 2),
                "spans_gap": spans_gap,
            }
        )
    return pd.DataFrame(events)


def rest_intervals(events: pd.DataFrame) -> pd.Series:
    """Time between the end of one event and the start of the next.

    Parameters
    ----------
    events : pd.DataFrame
        Output of extract_events(), must be time-sorted (it is, by
        construction).

    Returns
    -------
    pd.Series of rest durations in minutes (length = len(events) - 1).
    """
    if len(events) < 2:
        return pd.Series(dtype=float)
    gaps = (events["start"].iloc[1:].reset_index(drop=True)
            - events["end"].iloc[:-1].reset_index(drop=True))
    return (gaps.dt.total_seconds() / 60).rename("rest_minutes")


def event_duration_stats(events: pd.DataFrame) -> dict:
    """n / median / IQR of event durations, in seconds — for the boxplot."""
    if len(events) == 0:
        return {"n": 0, "median": None, "iqr": None}
    d = events["duration_s"]
    q1, med, q3 = d.quantile([0.25, 0.5, 0.75])
    return {"n": len(events), "median": round(med, 1), "iqr": [round(q1, 1), round(q3, 1)]}


def estimate_water_used(events: pd.DataFrame, flow_rate_l_per_min: float) -> float:
    """Estimated litres used = total spray minutes * flow rate.

    flow_rate_l_per_min must come from the hardware team; if unknown,
    treat it as a configurable assumption and state it in the report.
    """
    total_minutes = events["duration_min"].sum() if len(events) else 0.0
    return round(total_minutes * flow_rate_l_per_min, 2)


# ======================================================================
# effectiveness.py — Group D (extension): does spraying actually cool?
# ======================================================================
#
# Answers "does spraying actually cool the crop?" by comparing
# temperature immediately before each spray event to the minimum
# temperature in the following window. Comparing ON-state vs OFF-state
# temperature directly would be circular: the pump switches on BECAUSE
# it is hot, so of course ON periods look hotter. Before/after within
# each event avoids that.

def before_after_deltas(
    df: pd.DataFrame, events: pd.DataFrame, after_window_min: float = 10
) -> pd.DataFrame:
    """For each spray event, temperature just before it vs. min temp after.

    Returns
    -------
    pd.DataFrame with columns:
        event_start, temp_before, temp_min_after, delta
        (delta = temp_before - temp_min_after; positive = cooling happened)
    """
    rows = []
    for _, ev in events.iterrows():
        before = df[df["time"] <= ev["start"]]
        if before.empty:
            continue
        temp_before = before["temperature"].iloc[-1]

        after_end = ev["end"] + pd.Timedelta(minutes=after_window_min)
        after = df[(df["time"] >= ev["end"]) & (df["time"] <= after_end)]
        if after.empty:
            continue
        temp_min_after = after["temperature"].min()

        rows.append(
            {
                "event_start": ev["start"],
                "temp_before": temp_before,
                "temp_min_after": temp_min_after,
                "delta": round(temp_before - temp_min_after, 2),
            }
        )
    return pd.DataFrame(rows)


def delta_distribution(deltas: pd.DataFrame) -> dict:
    """Median/IQR of the before-after temperature delta."""
    if len(deltas) == 0:
        return {"n": 0, "median": None, "iqr": None}
    d = deltas["delta"]
    q1, med, q3 = d.quantile([0.25, 0.5, 0.75])
    return {"n": len(deltas), "median": round(med, 2), "iqr": [round(q1, 2), round(q3, 2)]}


def median_time_to_threshold(df: pd.DataFrame, events: pd.DataFrame, threshold: float):
    """Median minutes for temperature to fall back to `threshold` after
    a spray event ends. None if no events returned to threshold."""
    times = []
    for _, ev in events.iterrows():
        after = df[df["time"] >= ev["end"]]
        below = after[after["temperature"] <= threshold]
        if below.empty:
            continue
        minutes = (below["time"].iloc[0] - ev["end"]).total_seconds() / 60
        times.append(minutes)
    if not times:
        return None
    return round(pd.Series(times).median(), 1)


# ======================================================================
# profile.py — dataset profile (must run before any mean/correlation)
# ======================================================================

def profile_dataset(df: pd.DataFrame) -> dict:
    """Full profile of a loaded dataset (whole file or a window)."""
    dur = df["duration_s"].dropna()

    # per-day row counts, to spot missing/thin/heavy days
    daily_counts = df.set_index("time").resample("1D").size()

    profile = {
        "size_and_span": {
            "n_readings": len(df),
            "from": df["time"].min().isoformat(),
            "to": df["time"].max().isoformat(),
            "span_days": round((df["time"].max() - df["time"].min()).total_seconds() / 86400, 2),
        },
        "sampling": {
            "median_interval_s": round(dur.median(), 2),
            "min_interval_s": round(dur.min(), 4),
            "max_interval_s": round(dur.max(), 1),
            "evenly_spaced": bool(dur.std() < dur.median() * 0.1),  # rough flag, always inspect
        },
        "coverage": {
            "days_total": len(daily_counts),
            "days_with_zero_readings": int((daily_counts == 0).sum()),
            "min_readings_in_a_day": int(daily_counts.min()),
            "max_readings_in_a_day": int(daily_counts.max()),
            "median_readings_per_day": float(daily_counts.median()),
        },
        "shape": {
            col: {
                "mean": round(df[col].mean(), 2),
                "median": round(df[col].median(), 2),
                "skew": round(float(df[col].skew()), 3),
            }
            for col in ("temperature", "humidity")
        },
        "extremes": {
            col: _iqr_outliers(df[col]) for col in ("temperature", "humidity")
        },
        "columns": {
            col: {
                "n_unique": int(df[col].nunique()),
                "always_same_value": bool(df[col].nunique() <= 1),
                "percent_time_on": (
                    round(100 * (df["duration_s"].fillna(0) * df[col]).sum()
                          / df["duration_s"].fillna(0).sum(), 3)
                    if col.startswith("relay") else None
                ),
            }
            for col in ("relay1", "relay2", "relay3")
        },
    }
    return profile


def _iqr_outliers(series: pd.Series) -> dict:
    q1, q3 = series.quantile([0.25, 0.75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outliers = ((series < lo) | (series > hi)).sum()
    return {
        "min": float(series.min()),
        "max": float(series.max()),
        "iqr_fence_low": round(lo, 2),
        "iqr_fence_high": round(hi, 2),
        "n_outliers": int(outliers),
    }


# ======================================================================
# report.py — ties Groups A, B, C, D together into the weekly JSON
# ======================================================================

DEFAULT_CONFIG = {
    "temperature_threshold_c": 35.0,   # agreed stand-in stakeholder threshold
    "humidity_threshold_pct": 70.0,
    "pump_flow_rate_l_per_min": 2.0,   # ASSUMPTION — no hardware-team figure available
    "gap_threshold_s": 300,            # 5 minutes, per brief
    "effectiveness_window_min": 10,
}


def compute_weekly_report(df: pd.DataFrame, week_start, config: dict | None = None) -> dict:
    """Compute one week of statistics as a JSON-serialisable dict.

    Parameters
    ----------
    df : pd.DataFrame
        Full prepared dataset (output of load_data).
    week_start : str or pd.Timestamp
        Start of the week (Asia/Bangkok). The window is
        [week_start, week_start + 7 days).
    config : dict, optional
        Overrides for DEFAULT_CONFIG.

    Returns
    -------
    dict matching the project's JSON contract.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    week_start = pd.Timestamp(week_start)
    if week_start.tzinfo is None:
        week_start = week_start.tz_localize("Asia/Bangkok")
    week_end = week_start + pd.Timedelta(days=7)

    wdf = slice_window(df, week_start, week_end)
    warnings = []
    if len(wdf) == 0:
        warnings.append("No readings at all in this window.")
        return {
            "week_start": week_start.date().isoformat(),
            "week_end": week_end.date().isoformat(),
            "warnings": warnings,
        }

    # --- Group C first: everything else needs logged_duration_s ---
    uptime = compute_uptime(wdf, week_start, week_end, cfg["gap_threshold_s"])
    anomalies = timestamp_anomalies(wdf)

    # --- Group A ---
    temp = environment_summary(
        wdf, "temperature", cfg["temperature_threshold_c"], uptime["logged_duration_s"]
    )
    humidity = environment_summary(
        wdf, "humidity", cfg["humidity_threshold_pct"], uptime["logged_duration_s"]
    )

    # --- Group B ---
    relay1_duty = duty_cycle(wdf, "relay1", cfg["gap_threshold_s"])
    relay3_duty = duty_cycle(wdf, "relay3", cfg["gap_threshold_s"])
    spray_events = extract_events(wdf, "relay3", cfg["gap_threshold_s"])
    spray_activations = count_activations(wdf, "relay3")
    spray_rest = rest_intervals(spray_events)
    spray_duration_stats = event_duration_stats(spray_events)
    water_l = estimate_water_used(spray_events, cfg["pump_flow_rate_l_per_min"])

    # --- Group D (only if there is at least one spray event) ---
    if len(spray_events) > 0:
        deltas = before_after_deltas(wdf, spray_events, cfg["effectiveness_window_min"])
        delta_dist = delta_distribution(deltas)
        time_to_threshold = median_time_to_threshold(
            wdf, spray_events, cfg["temperature_threshold_c"]
        )
    else:
        delta_dist = {"n": 0, "median": None, "iqr": None}
        time_to_threshold = None
        warnings.append("Zero spray activations this week — Group D effectiveness cannot be computed.")

    if uptime["uptime_percent"] < 50:
        warnings.append(
            f"Logger uptime {uptime['uptime_percent']}%. Figures describe logged periods only."
        )
    if anomalies["n_duplicate_timestamps"] or anomalies["n_subsecond_intervals"]:
        warnings.append(
            f"{anomalies['n_subsecond_intervals']} sub-second reading interval(s) detected "
            "(burst/duplicate readings) — see data profile."
        )

    return {
        "week_start": week_start.date().isoformat(),
        "week_end": (week_end - pd.Timedelta(days=1)).date().isoformat(),
        "config": cfg,
        "coverage": {
            "uptime_percent": uptime["uptime_percent"],
            "gaps_over_5min": uptime["n_gaps"],
            "total_gap_hours": uptime["total_gap_hours"],
            "n_readings": len(wdf),
        },
        "temperature_c": temp,
        "humidity_pct": humidity,
        "relay1_cooling": {
            "duty_cycle_percent": relay1_duty["duty_cycle_percent"],
            "on_minutes": relay1_duty["on_minutes"],
        },
        "spray": {
            "activations": spray_activations,
            "duty_cycle_percent": relay3_duty["duty_cycle_percent"],
            "total_minutes": relay3_duty["on_minutes"],
            "event_duration_seconds": spray_duration_stats,
            "rest_minutes_median": round(spray_rest.median(), 1) if len(spray_rest) else None,
            "estimated_litres": water_l,
        },
        "effectiveness": {
            "n_events_analysed": delta_dist["n"],
            "temp_drop_c_median": delta_dist["median"],
            "temp_drop_c_iqr": delta_dist["iqr"],
            "median_minutes_to_threshold": time_to_threshold,
        },
        "warnings": warnings,
    }


# ======================================================================
# make_deliverables — full profile JSONs + the 4 report figures
# ======================================================================

def make_deliverables(csv_path: str, week_start: str = "2026-05-11", out_dir: str = "."):
    """Reproduce every deliverable: full_dataset_profile.json,
    week2_profile.json, week2_report.json, and figures/fig1..fig4.png.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = load_data(csv_path)
    week_end = (pd.Timestamp(week_start) + pd.Timedelta(days=7)).date().isoformat()

    figures_dir = os.path.join(out_dir, "figures")
    os.makedirs(figures_dir, exist_ok=True)

    # --- whole-dataset profile ---
    full_profile = profile_dataset(df)
    with open(os.path.join(out_dir, "full_dataset_profile.json"), "w") as f:
        json.dump(full_profile, f, indent=2, default=str)

    # --- week window ---
    wdf = slice_window(df, week_start, week_end)
    week_profile = profile_dataset(wdf)
    with open(os.path.join(out_dir, "week2_profile.json"), "w") as f:
        json.dump(week_profile, f, indent=2, default=str)

    report = compute_weekly_report(df, week_start)
    with open(os.path.join(out_dir, "week2_report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)

    # --- Figure 1: temperature histogram ---
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(wdf["temperature"], bins=30, color="#c0392b", edgecolor="white")
    ax.axvline(wdf["temperature"].median(), color="black", linestyle="--",
               label=f"median {wdf['temperature'].median():.1f}C")
    ax.axvline(wdf["temperature"].mean(), color="gray", linestyle=":",
               label=f"mean {wdf['temperature'].mean():.1f}C")
    ax.set_xlabel("Temperature (C)")
    ax.set_ylabel("Count")
    ax.set_title(f"Temperature distribution, week of {week_start}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(figures_dir, "fig1_temperature_hist.png"), dpi=150)
    plt.close(fig)

    # --- Figure 2: humidity histogram ---
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(wdf["humidity"], bins=30, color="#2980b9", edgecolor="white")
    ax.axvline(wdf["humidity"].median(), color="black", linestyle="--",
               label=f"median {wdf['humidity'].median():.1f}%")
    ax.axvline(wdf["humidity"].mean(), color="gray", linestyle=":",
               label=f"mean {wdf['humidity'].mean():.1f}%")
    ax.set_xlabel("Humidity (%)")
    ax.set_ylabel("Count")
    ax.set_title(f"Humidity distribution, week of {week_start}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(figures_dir, "fig2_humidity_hist.png"), dpi=150)
    plt.close(fig)

    # --- Figure 3: spray-event duration boxplot ---
    events = extract_events(wdf, "relay3")
    fig, ax = plt.subplots(figsize=(4, 5))
    if len(events):
        ax.boxplot(events["duration_s"], vert=True)
    ax.set_ylabel("Spray event duration (s)")
    ax.set_title(f"Spray event durations (n={len(events)})")
    fig.tight_layout()
    fig.savefig(os.path.join(figures_dir, "fig3_spray_duration_boxplot.png"), dpi=150)
    plt.close(fig)

    # --- Figure 4: temperature time series with spray events + threshold ---
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(wdf["time"], wdf["temperature"], color="#c0392b", linewidth=0.8)
    for _, ev in events.iterrows():
        ax.axvspan(ev["start"], ev["end"], color="#2980b9", alpha=0.4)
    ax.axhline(35.0, color="gray", linestyle="--", linewidth=0.8, label="threshold 35C")
    ax.set_ylabel("Temperature (C)")
    ax.set_title(f"Temperature with spray events (blue) — week of {week_start}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(figures_dir, "fig4_temp_timeseries_with_sprays.png"), dpi=150)
    plt.close(fig)

    print("Done. Figures in figures/, JSON in current dir.")
    print("Full dataset days with zero readings:", full_profile["coverage"]["days_with_zero_readings"])
    print("Week events n =", len(events))


# ======================================================================
# CLI
# ======================================================================

def main():
    parser = argparse.ArgumentParser(description="Compute the FarmOS weekly report (single-file version).")
    parser.add_argument("--csv", required=True, help="Path to the raw sensor CSV.")
    parser.add_argument("--start", default="2026-05-11", help="Week start date, e.g. 2026-05-11.")
    parser.add_argument("--out", default="week2_report.json", help="Output JSON path (report mode).")
    parser.add_argument("--threshold", type=float, default=None, help="Temperature threshold, C.")
    parser.add_argument("--flow-rate", type=float, default=None, help="Pump flow rate, L/min.")
    parser.add_argument("--deliverables", action="store_true",
                         help="Also produce full_dataset_profile.json, week2_profile.json and figures/*.png.")
    args = parser.parse_args()

    if args.deliverables:
        make_deliverables(args.csv, args.start)
        return

    df = load_data(args.csv)

    config = {}
    if args.threshold is not None:
        config["temperature_threshold_c"] = args.threshold
    if args.flow_rate is not None:
        config["pump_flow_rate_l_per_min"] = args.flow_rate

    report = compute_weekly_report(df, args.start, config)

    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Report written to {args.out}")
    print(f"  week: {report['week_start']} to {report.get('week_end')}")
    if "coverage" in report:
        print(f"  uptime: {report['coverage']['uptime_percent']}%")
        print(f"  temperature median: {report['temperature_c']['median']} C")
        print(f"  spray activations: {report['spray']['activations']}")


if __name__ == "__main__":
    main()

"""
FarmOS Weekly Farm Report Generator
------------------------------------
Single-file implementation containing:
1. Core statistical calculation engine (compute_weekly_report)
2. Command-Line Interface (CLI)
3. Embedded Unit Tests (--test flag)
"""

import argparse
import json
import sys
import unittest
import numpy as np
import pandas as pd


def compute_weekly_report(df: pd.DataFrame, week_start: str, config: dict = None) -> dict:
    """
    Computes one week of statistics as a JSON-serialisable dictionary.

    Parameters:
    -----------
    df : pd.DataFrame
        Raw dataset containing ['time', 'temperature', 'humidity', 'relay1', 'relay2', 'relay3']
    week_start : str
        Start date of the target week in format 'YYYY-MM-DD'
    config : dict, optional
        Configuration dictionary containing parameters:
        - temp_threshold: float (default 35.0)
        - flow_rate_lpm: float (default 5.0)
        - gap_threshold_sec: float (default 300.0)

    Returns:
    --------
    dict : Structured dictionary containing metrics, coverage, and warnings.
    """
    if config is None:
        config = {}

    temp_threshold = config.get("temp_threshold", 35.0)
    flow_rate = config.get("flow_rate_lpm", 5.0)
    gap_threshold = config.get("gap_threshold_sec", 300.0)

    # 1. Parse timestamps and sort chronologically
    df = df.copy()
    df["time_dt"] = pd.to_datetime(df["time"], format="mixed").dt.tz_convert("Asia/Bangkok")
    df = df.sort_values("time_dt").reset_index(drop=True)

    # 2. Filter target week window (7 full days)
    start_dt = pd.to_datetime(week_start).tz_localize("Asia/Bangkok")
    end_dt = start_dt + pd.Timedelta(days=7)
    week_df = df[(df["time_dt"] >= start_dt) & (df["time_dt"] < end_dt)].copy()

    warnings = []

    if week_df.empty:
        return {
            "week_start": week_start,
            "week_end": (start_dt + pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
            "coverage": {"uptime_percent": 0.0, "gaps_over_5min": 0, "total_logged_seconds": 0},
            "warnings": ["No data available for the specified week."]
        }

    # 3. Calculate row durations (delta_t)
    week_df["duration_sec"] = week_df["time_dt"].diff().shift(-1).dt.total_seconds()

    # Fill last sample duration with median sample duration
    median_interval = week_df["duration_sec"].median()
    if pd.isna(median_interval) or median_interval <= 0:
        median_interval = 30.0
    week_df["duration_sec"] = week_df["duration_sec"].fillna(median_interval)

    # 4. Data Health Metrics (Group C)
    total_week_sec = 7 * 24 * 3600.0  # 604,800 seconds
    total_logged_sec = week_df["duration_sec"].sum()
    uptime_pct = min(100.0, (total_logged_sec / total_week_sec) * 100)

    gaps_df = week_df[week_df["duration_sec"] > gap_threshold]
    num_gaps = len(gaps_df)

    if uptime_pct < 80.0:
        warnings.append(f"Logger uptime is low ({uptime_pct:.1f}%). Statistics describe logged periods only.")
    if num_gaps > 0:
        warnings.append(f"Detected {num_gaps} data outage gaps longer than 5 minutes.")

    # 5. Environment Metrics (Group A)
    # Temperature (Median & IQR)
    t_med = float(week_df["temperature"].median())
    t_q25 = float(week_df["temperature"].quantile(0.25))
    t_q75 = float(week_df["temperature"].quantile(0.75))
    t_iqr = float(t_q75 - t_q25)
    t_max = float(week_df["temperature"].max())
    t_min = float(week_df["temperature"].min())
    
    t_max_idx = week_df["temperature"].idxmax()
    t_max_time = week_df.loc[t_max_idx, "time_dt"].isoformat() if pd.notna(t_max_idx) else None

    # Time above temperature threshold
    above_thresh = week_df[week_df["temperature"] > temp_threshold]
    time_above_sec = above_thresh["duration_sec"].sum()
    pct_above = (time_above_sec / total_logged_sec) * 100 if total_logged_sec > 0 else 0.0

    # Humidity (Median & IQR)
    h_med = float(week_df["humidity"].median())
    h_q25 = float(week_df["humidity"].quantile(0.25))
    h_q75 = float(week_df["humidity"].quantile(0.75))
    h_iqr = float(h_q75 - h_q25)

    # 6. Actuator Behavior Metrics (Group B - Time Weighted)
    r1_on_sec = week_df[week_df["relay1"] == 1]["duration_sec"].sum()
    r1_duty_cycle = (r1_on_sec / total_logged_sec) * 100 if total_logged_sec > 0 else 0.0

    r3_on_sec = week_df[week_df["relay3"] == 1]["duration_sec"].sum()
    r3_duty_cycle = (r3_on_sec / total_logged_sec) * 100 if total_logged_sec > 0 else 0.0
    r3_total_minutes = r3_on_sec / 60.0
    estimated_water_litres = r3_total_minutes * flow_rate

    # Count OFF -> ON activations
    activations = int((week_df["relay3"].diff() == 1).sum())
    if week_df.iloc[0]["relay3"] == 1:
        activations += 1  # Count initial active state

    # Spray Event Duration Analysis
    week_df["event_id"] = (week_df["relay3"] != week_df["relay3"].shift()).cumsum()
    spray_events = week_df[week_df["relay3"] == 1].groupby("event_id").agg(
        duration=("duration_sec", "sum")
    )

    if not spray_events.empty:
        ev_med = float(spray_events["duration"].median())
        ev_q25 = float(spray_events["duration"].quantile(0.25))
        ev_q75 = float(spray_events["duration"].quantile(0.75))
        ev_iqr = float(ev_q75 - ev_q25)
    else:
        ev_med, ev_iqr = 0.0, 0.0

    # 7. Output Payload Structure
    report = {
        "week_start": week_start,
        "week_end": (start_dt + pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
        "coverage": {
            "uptime_percent": round(uptime_pct, 2),
            "gaps_over_5min_note ": num_gaps, 
            # 168h / week 
            "total_hours": round(total_logged_sec / 3600.0, 2)
        },
        "temperature_c": {
            "median": round(t_med, 2),
            "IQR": round(t_iqr, 2),
            "Min": round(t_min, 2),
            "Max": round(t_max, 2),
            "Max_at": t_max_time,
            "threshold_c": temp_threshold,
            "percent_time_above_threshold": round(pct_above, 2)
        },
        "humidity_percent": {
            "Median": round(h_med, 2),
            "IQR": round(h_iqr, 2)
        },
        "actuators": {
            "relay1_cooling_duty_cycle_percent": round(r1_duty_cycle, 2),
            "relay3_spray_duty_cycle_percent": round(r3_duty_cycle, 2),
            "pump_activations_total": activations,
            "total_water_spray_minutes": round(r3_total_minutes, 2),
            "estimated_water_litres": round(estimated_water_litres, 2),
            "spray_event_duration_seconds": {
                "Median": round(ev_med, 1),
                "IQR": round(ev_iqr, 1)
            }
        },
        "warnings": warnings
    }

    return report


# Embedded Unit Test Suite
class TestGreenhouseStats(unittest.TestCase):

    def setUp(self):
        self.fixture_data = {
            'time': [
                '2026-05-11 10:00:00+07',  # 60s
                '2026-05-11 10:01:00+07',  # 540s (gap)
                '2026-05-11 10:10:00+07',  # 60s
                '2026-05-11 10:11:00+07',  # 60s
                '2026-05-11 10:12:00+07',  # 60s
            ],
            'temperature': [34.0, 36.0, 37.0, 33.0, 32.0],
            'humidity': [60.0, 55.0, 50.0, 65.0, 70.0],
            'relay1': [1, 1, 0, 0, 0],
            'relay2': [0, 0, 0, 0, 0],
            'relay3': [1, 0, 0, 1, 0]
        }
        self.df = pd.DataFrame(self.fixture_data)
        self.config = {"temp_threshold": 35.0, "flow_rate_lpm": 5.0, "gap_threshold_sec": 300.0}

    def test_time_weighted_duty_cycle(self):
        report = compute_weekly_report(self.df, "2026-05-11", self.config)
        calculated_duty_cycle = report["actuators"]["relay3_spray_duty_cycle_percent"]
        self.assertAlmostEqual(calculated_duty_cycle, 15.38, places=2)

    def test_gap_detection(self):
        report = compute_weekly_report(self.df, "2026-05-11", self.config)
        self.assertEqual(report["coverage"]["gaps_over_5min"], 1)

    def test_pump_activations_count(self):
        report = compute_weekly_report(self.df, "2026-05-11", self.config)
        self.assertEqual(report["actuators"]["pump_activations"], 2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FarmOS Weekly Farm Report Generator")
    parser.add_argument("--file", type=str, default="Automated Cooling and Spraying Data.csv", help="Input CSV path")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--out", type=str, default="weekly_report.json", help="Output JSON path")
    parser.add_argument("--test", action="store_true", help="Run embedded unit tests")

    args = parser.parse_args()

    if args.test:
        print("Running unit tests...")
        suite = unittest.TestLoader().loadTestsFromTestCase(TestGreenhouseStats)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        sys.exit(not result.wasSuccessful())

    if not args.start:
        parser.error("Please provide --start date (e.g., --start 2026-05-11) or use --test to run unit tests.")

    df_data = pd.read_csv(args.file)
    cfg = {"temp_threshold": 35.0, "flow_rate_lpm": 5.0, "gap_threshold_sec": 300.0}

    report_output = compute_weekly_report(df_data, week_start=args.start, config=cfg)

    with open(args.out, "w") as f:
        json.dump(report_output, f, indent=2)

    print(f"Report successfully saved to {args.out}")

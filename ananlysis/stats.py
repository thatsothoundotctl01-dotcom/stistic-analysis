"""
Greenhouse Analytics Module for FarmOS
--------------------------------------
Calculates time-weighted stats, environment metrics (Median/IQR), 
actuator behaviour, and data coverage for weekly farm reports.
"""

import argparse
import json
import numpy as np
import pandas as pd


def compute_weekly_report(df: pd.DataFrame, week_start: str, config: dict) -> dict:
    """
    Computes a weekly statistics report for FarmOS based on raw CSV readings.

    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame containing ['time', 'temperature', 'humidity', 'relay1', 'relay2', 'relay3']
    week_start : str
        Start date string of the target week (e.g., '2026-05-11')
    config : dict
        Configuration dictionary containing:
        - temp_threshold: float (default 35.0 °C)
        - flow_rate_lpm: float (default 10.0 L/min)
        - gap_threshold_sec: float (default 300.0 sec / 5 mins)

    Returns:
    --------
    dict : JSON-serializable dictionary containing report metrics and warnings.
    """
    df = df.copy()

    # 1. Parse timestamps (format='mixed') & set timezone to Asia/Bangkok (+07)
    df['time_dt'] = pd.to_datetime(df['time'], format='mixed')
    if df['time_dt'].dt.tz is None:
        df['time_dt'] = df['time_dt'].dt.tz_localize('Asia/Bangkok')
    else:
        df['time_dt'] = df['time_dt'].dt.tz_convert('Asia/Bangkok')

    df = df.sort_values('time_dt').reset_index(drop=True)

    # Define week boundaries
    start_dt = pd.to_datetime(week_start)
    if start_dt.tzinfo is None:
        start_dt = start_dt.tz_localize('Asia/Bangkok')
    else:
        start_dt = start_dt.tz_convert('Asia/Bangkok')
    end_dt = start_dt + pd.Timedelta(days=7)

    # Filter for the target 7-day window
    df_week = df[(df['time_dt'] >= start_dt) & (df['time_dt'] < end_dt)].copy()

    if df_week.empty:
        return {
            "week_start": week_start,
            "error": "No readings found for the specified week window.",
            "warnings": ["No data available for the requested period."]
        }

    # Configuration values
    temp_threshold = config.get("temp_threshold", 35.0)
    flow_rate_lpm = config.get("flow_rate_lpm", 10.0)
    max_gap_sec = config.get("gap_threshold_sec", 300.0)  # 5 minutes

    # 2. Section 8 Requirement: Time-weighting duration per reading
    df_week['duration_sec'] = df_week['time_dt'].diff().shift(-1).dt.total_seconds()

    # Data Health & Coverage Metrics
    gaps = df_week[df_week['duration_sec'] > max_gap_sec]
    gaps_count = len(gaps)
    total_gap_sec = gaps['duration_sec'].sum() if gaps_count > 0 else 0.0

    total_week_seconds = 7 * 24 * 3600.0
    valid_readings = df_week[df_week['duration_sec'] <= max_gap_sec]
    logged_seconds = valid_readings['duration_sec'].sum()
    uptime_percent = round((logged_seconds / total_week_seconds) * 100.0, 2)

    # 3. Group A Metrics — Environment (Median & IQR)
    temp_median = float(df_week['temperature'].median())
    temp_q1 = float(df_week['temperature'].quantile(0.25))
    temp_q3 = float(df_week['temperature'].quantile(0.75))
    temp_iqr = [round(temp_q1, 2), round(temp_q3, 2)]

    temp_min = float(df_week['temperature'].min())
    temp_min_at = df_week.loc[df_week['temperature'].idxmin()]['time_dt'].isoformat()
    temp_max = float(df_week['temperature'].max())
    temp_max_at = df_week.loc[df_week['temperature'].idxmax()]['time_dt'].isoformat()

    hum_median = float(df_week['humidity'].median())
    hum_q1 = float(df_week['humidity'].quantile(0.25))
    hum_q3 = float(df_week['humidity'].quantile(0.75))
    hum_iqr = [round(hum_q1, 2), round(hum_q3, 2)]

    # Time-weighted % time above threshold
    above_thresh_sec = valid_readings[valid_readings['temperature'] > temp_threshold]['duration_sec'].sum()
    pct_time_above = round((above_thresh_sec / logged_seconds) * 100.0, 2) if logged_seconds > 0 else 0.0

    # Longest continuous heat spell
    df_week['is_above'] = df_week['temperature'] > temp_threshold
    df_week['spell_id'] = (df_week['is_above'] != df_week['is_above'].shift()).cumsum()
    above_spells = df_week[df_week['is_above']].groupby('spell_id')['duration_sec'].sum()
    longest_spell_min = round(float(above_spells.max()) / 60.0, 2) if not above_spells.empty else 0.0

    # 4. Group B Metrics — Actuator Behavior (Time-weighted Duty Cycle)
    relay1_on_sec = valid_readings[valid_readings['relay1'] == 1]['duration_sec'].sum()
    relay1_duty = round((relay1_on_sec / logged_seconds) * 100.0, 2) if logged_seconds > 0 else 0.0

    relay3_on_sec = valid_readings[valid_readings['relay3'] == 1]['duration_sec'].sum()
    relay3_duty = round((relay3_on_sec / logged_seconds) * 100.0, 2) if logged_seconds > 0 else 0.0

    # Count OFF -> ON activations
    relay3_activations = int((df_week['relay3'].diff() == 1).sum())

    total_spray_minutes = round(relay3_on_sec / 60.0, 2)
    estimated_water_litres = round(total_spray_minutes * flow_rate_lpm, 2)

    # Event duration distribution
    df_week['event_id'] = (df_week['relay3'] != df_week['relay3'].shift()).cumsum()
    spray_events = df_week[df_week['relay3'] == 1].groupby('event_id')['duration_sec'].sum()

    if not spray_events.empty:
        spray_event_dur_stats = {
            "n": len(spray_events),
            "median_sec": round(float(spray_events.median()), 2),
            "iqr_sec": [round(float(spray_events.quantile(0.25)), 2), round(float(spray_events.quantile(0.75)), 2)]
        }
    else:
        spray_event_dur_stats = {"n": 0, "median_sec": 0.0, "iqr_sec": [0.0, 0.0]}

    # 5. Populate Warnings
    warnings = []
    if uptime_percent < 90.0:
        warnings.append(f"Logger uptime is low ({uptime_percent}%). Figures describe logged periods only.")
    if gaps_count > 0:
        warnings.append(f"Detected {gaps_count} logger gap(s) exceeding 5 minutes.")
    if pct_time_above > 40.0:
        warnings.append(f"High heat warning: Temperature exceeded {temp_threshold}°C for {pct_time_above}% of logged time.")

    # Contract JSON
    return {
        "week_start": week_start,
        "week_end": (start_dt + pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
        "coverage": {
            "uptime_percent": uptime_percent,
            "gaps_over_5min_count": gaps_count,
            "total_gap_duration_minutes": round(total_gap_sec / 60.0, 2)
        },
        "temperature_c": {
            "median": temp_median,
            "iqr": temp_iqr,
            "min": temp_min,
            "min_at": temp_min_at,
            "max": temp_max,
            "max_at": temp_max_at,
            "threshold_c": temp_threshold,
            "percent_time_above_threshold": pct_time_above,
            "longest_heat_spell_minutes": longest_spell_min
        },
        "humidity_percent": {
            "median": hum_median,
            "iqr": hum_iqr
        },
        "actuators": {
            "relay1_cooling_duty_cycle_percent": relay1_duty,
            "relay3_spray_duty_cycle_percent": relay3_duty,
            "spray_activations": relay3_activations,
            "total_spray_minutes": total_spray_minutes,
            "estimated_water_litres": estimated_water_litres,
            "spray_event_duration": spray_event_dur_stats
        },
        "warnings": warnings
    }


def run_unit_tests():
    """Runs hand-crafted unit tests to verify calculations."""
    print("Running Unit Tests...")

    # Test 1: Time-weighted duty cycle vs row mean
    test_df = pd.DataFrame({
        'time': ['2026-05-11 10:00:00+07', '2026-05-11 10:00:10+07', '2026-05-11 10:01:40+07'],
        'temperature': [30.0, 31.0, 30.0],
        'humidity': [60.0, 60.0, 60.0],
        'relay1': [0, 0, 0],
        'relay2': [0, 0, 0],
        'relay3': [1, 0, 0]
    })
    res = compute_weekly_report(test_df, '2026-05-11', {})
    assert res['actuators']['relay3_spray_duty_cycle_percent'] == 10.0, "Test 1 Failed"
    print("✓ Test 1 Passed: Time-weighted duty cycle correctly calculated (10.0%).")

    # Test 2: Activations count (OFF -> ON)
    test_df2 = pd.DataFrame({
        'time': ['2026-05-11 10:00:00+07', '2026-05-11 10:00:30+07', '2026-05-11 10:01:00+07', '2026-05-11 10:01:30+07'],
        'temperature': [32, 32, 32, 32],
        'humidity': [50, 50, 50, 50],
        'relay1': [0, 0, 0, 0],
        'relay2': [0, 0, 0, 0],
        'relay3': [0, 1, 0, 1]
    })
    res2 = compute_weekly_report(test_df2, '2026-05-11', {})
    assert res2['actuators']['spray_activations'] == 2, "Test 2 Failed"
    print("✓ Test 2 Passed: Actuator activations correctly counted (2 activations).")

    # Test 3: Median resilience against outlier
    test_df3 = pd.DataFrame({
        'time': [f'2026-05-11 10:0{i}:00+07' for i in range(5)],
        'temperature': [20.0, 25.0, 30.0, 35.0, 100.0],
        'humidity': [50, 50, 50, 50, 50],
        'relay1': [0, 0, 0, 0, 0],
        'relay2': [0, 0, 0, 0, 0],
        'relay3': [0, 0, 0, 0, 0]
    })
    res3 = compute_weekly_report(test_df3, '2026-05-11', {})
    assert res3['temperature_c']['median'] == 30.0, "Test 3 Failed"
    print("✓ Test 3 Passed: Median resistant to outliers (Median = 30.0).\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Generate Weekly FarmOS JSON Report")
    parser.add_argument('--csv', type=str, default='Automated Cooling and Spraying Data.csv', help='Path to CSV')
    parser.add_argument('--start', type=str, default='2026-05-11', help='Start date YYYY-MM-DD')
    parser.add_argument('--out', type=str, default='week_report.json', help='Output JSON path')
    parser.add_argument('--test', action='store_true', help='Run unit tests')

    args = parser.parse_args()

    if args.test:
        run_unit_tests()
    else:
        df_raw = pd.read_csv(args.csv)
        report_data = compute_weekly_report(df_raw, args.start, {"temp_threshold": 35.0, "flow_rate_lpm": 10.0})
        with open(args.out, 'w') as f:
            json.dump(report_data, f, indent=2)
        print(f"Report successfully generated and saved to '{args.out}'.") 

        # how to run it 
        # this command 
        #
        #
        #
        #
        #
        #
        # python3 stats.py --csv "Automated Cooling and Spraying Data.csv" --start 2026-05-11 --out week_20.json
